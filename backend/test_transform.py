"""TASK-004 proof: Phase 3 data-cleaning transforms + snapshot undo/redo.

Standalone, idempotent (AP-7): it tears down its own fixtures at the start, so
it can be run twice consecutively with identical results. It announces the live
Redis backend (AP-9) -- if that is not `redis`, the cache-touching proof is void.

Covers every TASK-004 acceptance criterion with real, printed output:
  1. each of the 5 ops on a real table, with the compiled DuckDB SQL + real effect
  2. undo restores the exact prior state (row count + schema); redo re-applies
  3. per-table independence (op on A leaves B untouched)
  4. malicious calculated_column formula rejected; sentinel table survives
  5. schema_version increments; GET /schema reflects post-transform types (HTTP leg)
  6. snapshot cap enforced (oldest dropped past the cap)
  7. real Redis, runnable twice
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
from services import transform_service
from routers.session import (
    analyze_and_register_table,
    refresh_table_schema_cache,
    _table_name_for,
)
from models.schemas import (
    TransformDedupe,
    TransformDropNull,
    TransformImputeNull,
    TransformCast,
    TransformCalculatedColumn,
)

S_A = "test-transform-a"
S_B = "test-transform-b"
S_C = "test-transform-c"
SENTINEL = "sentinel_survivor"

# region,revenue,cost -- row 2 is an exact dup of row 1; South has a null cost.
CSV_PRIMARY = (
    "region,revenue,cost\n"
    "North,100,60\n"
    "North,100,60\n"
    "South,200,\n"
    "West,150,50\n"
    "East,300,100\n"
)

_failures = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(label)
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


async def _drop_like(pattern):
    rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE ?",
        (pattern,),
    )
    for (tn,) in rows or []:
        await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{tn}"')


def _redis_cleanup(*sessions):
    c = redis_manager.client
    for s in sessions:
        c.delete(f"schema:{s}")
        c.delete(f"schema_version:{s}")
        for k in c.keys(f"history:{s}:*"):
            c.delete(k)


async def _teardown():
    # Anything our fixtures could have created, live tables + backups + tmp swaps.
    await _drop_like("%test_transform%")
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{SENTINEL}"')
    _redis_cleanup(S_A, S_B, S_C)


def _write_csv(name, body):
    os.makedirs("uploads/_tasktest", exist_ok=True)
    path = f"uploads/_tasktest/{name}"
    with open(path, "w", newline="") as f:
        f.write(body)
    return path


async def _rowcount(tbl):
    return (await db_manager.run_readwrite(f'SELECT COUNT(*) FROM "{tbl}"'))[0][0]


async def _coltype(tbl, col):
    info = await db_manager.run_readwrite(f'PRAGMA table_info("{tbl}")')
    for row in info:
        if row[1] == col:
            return row[2]
    return None


async def _cell(tbl, col, where_col, where_val):
    res = await db_manager.run_readwrite(
        f'SELECT "{col}" FROM "{tbl}" WHERE "{where_col}" = ?', (where_val,)
    )
    return res[0][0] if res else None


async def _reset_to_pristine(session, tbl):
    """Undo until nothing is left to undo, so a demo starts from state 0."""
    while transform_service.get_history(session, tbl)["can_undo"]:
        await transform_service.undo(session, tbl)


async def service_main():
    print("=" * 70)
    print("TASK-004 PROOF -- transforms + snapshot undo/redo")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    await _teardown()

    # Register two independent tables in session A and one in B.
    path_a = _write_csv("primary.csv", CSV_PRIMARY)
    tname_a, _ = _table_name_for(S_A, "primary.csv")
    await analyze_and_register_table(S_A, tname_a, path_a, is_primary=True)

    tname_b, _ = _table_name_for(S_B, "primary.csv")
    await analyze_and_register_table(S_B, tname_b, path_a, is_primary=True)

    base_rows = await _rowcount(tname_a)
    print(f"\nRegistered {tname_a} with {base_rows} rows (2 identical, 1 null cost).")

    cols = await transform_service._columns_of(tname_a)

    # --- Criterion 1: each op, compiled SQL + real effect (each from pristine) ---
    print("\n--- 1. Each transform op (compiled DuckDB SQL + real effect) ---")

    # dedupe
    p = TransformDedupe(op="dedupe")
    print("\n[dedupe] compiled SQL:")
    print("    " + transform_service._compile_structured(tname_a, cols, p))
    _, _, rc = await transform_service.apply_transform(S_A, tname_a, p)
    check("dedupe drops the duplicate row (5 -> 4)", rc == 4, f"row_count={rc}")
    await _reset_to_pristine(S_A, tname_a)
    check("undo-to-pristine restores 5 rows after dedupe", await _rowcount(tname_a) == 5)

    # drop_null
    p = TransformDropNull(op="drop_null", column="cost")
    print("\n[drop_null cost] compiled SQL:")
    print("    " + transform_service._compile_structured(tname_a, cols, p))
    _, _, rc = await transform_service.apply_transform(S_A, tname_a, p)
    check("drop_null(cost) removes the 1 null-cost row (5 -> 4)", rc == 4, f"row_count={rc}")
    await _reset_to_pristine(S_A, tname_a)

    # impute_null zero
    p = TransformImputeNull(op="impute_null", column="cost", strategy="zero")
    print("\n[impute_null cost=zero] compiled SQL:")
    print("    " + transform_service._compile_structured(tname_a, cols, p))
    await transform_service.apply_transform(S_A, tname_a, p)
    south = await _cell(tname_a, "cost", "region", "South")
    check("impute zero fills South's null cost with 0", south == 0, f"cost={south}")
    check("impute keeps row count at 5", await _rowcount(tname_a) == 5)
    await _reset_to_pristine(S_A, tname_a)

    # impute_null custom
    p = TransformImputeNull(op="impute_null", column="cost", strategy="custom", fill_value=999)
    await transform_service.apply_transform(S_A, tname_a, p)
    south = await _cell(tname_a, "cost", "region", "South")
    check("impute custom=999 fills South's null cost with 999", south == 999, f"cost={south}")
    await _reset_to_pristine(S_A, tname_a)

    # impute_null mean (aggregate path)
    p = TransformImputeNull(op="impute_null", column="cost", strategy="mean")
    await transform_service.apply_transform(S_A, tname_a, p)
    nulls = (await db_manager.run_readwrite(
        f'SELECT COUNT(*) FROM "{tname_a}" WHERE "cost" IS NULL'))[0][0]
    check("impute mean leaves no null cost", nulls == 0, f"null_cost_rows={nulls}")
    await _reset_to_pristine(S_A, tname_a)

    # cast
    p = TransformCast(op="cast", column="revenue", new_type="DOUBLE")
    print("\n[cast revenue->DOUBLE] compiled SQL:")
    print("    " + transform_service._compile_structured(tname_a, cols, p))
    before_type = await _coltype(tname_a, "revenue")
    await transform_service.apply_transform(S_A, tname_a, p)
    after_type = await _coltype(tname_a, "revenue")
    check("cast changes revenue type BIGINT -> DOUBLE",
          before_type != after_type and "DOUBLE" in after_type.upper(),
          f"{before_type} -> {after_type}")
    await _reset_to_pristine(S_A, tname_a)

    # calculated_column (positive)
    p = TransformCalculatedColumn(op="calculated_column", new_column_name="profit", formula="revenue - cost")
    print("\n[calculated_column profit = revenue - cost] compiled SQL:")
    print("    " + transform_service._build_calc_sql(tname_a, cols, p))
    await transform_service.apply_transform(S_A, tname_a, p)
    north_profit = await _cell(tname_a, "profit", "region", "North")
    check("calculated_column profit present and correct (North: 100-60=40)",
          north_profit == 40, f"North profit={north_profit}")
    await _reset_to_pristine(S_A, tname_a)

    # --- Criterion 2: undo restores exact prior state; redo re-applies ---
    print("\n--- 2. Undo restores exact prior state; redo re-applies ---")
    await _reset_to_pristine(S_A, tname_a)
    await transform_service.apply_transform(S_A, tname_a, TransformDedupe(op="dedupe"))
    rows_after_dedupe = await _rowcount(tname_a)
    await transform_service.apply_transform(
        S_A, tname_a, TransformCast(op="cast", column="revenue", new_type="DOUBLE"))
    type_after_cast = await _coltype(tname_a, "revenue")

    _, _, rc = await transform_service.undo(S_A, tname_a)
    check("undo reverts the cast: revenue type back to non-DOUBLE",
          "DOUBLE" not in (await _coltype(tname_a, "revenue")).upper(),
          f"type now {await _coltype(tname_a, 'revenue')}")
    check("undo restores exact prior row count (dedupe state)",
          rc == rows_after_dedupe, f"row_count={rc}")

    _, _, rc = await transform_service.redo(S_A, tname_a)
    check("redo re-applies the cast: revenue DOUBLE again",
          "DOUBLE" in (await _coltype(tname_a, "revenue")).upper(),
          f"type now {await _coltype(tname_a, 'revenue')}")

    # --- Criterion 3: per-table independence ---
    print("\n--- 3. Per-table independence (session A vs B) ---")
    b_before = await _rowcount(tname_b)
    await _reset_to_pristine(S_A, tname_a)
    await transform_service.apply_transform(S_A, tname_a, TransformDedupe(op="dedupe"))
    await transform_service.undo(S_A, tname_a)
    b_after = await _rowcount(tname_b)
    check("table B row count unaffected by transforms on A", b_before == b_after,
          f"B: {b_before} -> {b_after}")
    check("table B has no transform history of its own",
          transform_service.get_history(S_B, tname_b)["total_steps"] == 0)

    # --- Criterion 4: malicious formula rejected, sentinel survives ---
    print("\n--- 4. Malicious calculated_column formula rejected ---")
    await db_manager.run_readwrite(f'CREATE TABLE "{SENTINEL}" (id INTEGER)')
    await db_manager.run_readwrite(f'INSERT INTO "{SENTINEL}" VALUES (1)')

    attacks = {
        "statement injection (1); DROP TABLE ...; --": f"1); DROP TABLE {SENTINEL}; --",
        "scalar subquery (SELECT 1)": "(SELECT 1)",
        "unknown column reference": "nonexistent_col + 1",
        "stacked statement": "revenue; DROP TABLE x",
    }
    for label, formula in attacks.items():
        rejected = False
        try:
            await transform_service.apply_transform(
                S_A, tname_a,
                TransformCalculatedColumn(op="calculated_column", new_column_name="evil", formula=formula),
            )
        except transform_service.TransformError as exc:
            rejected = True
            reason = str(exc)
        check(f"rejected: {label}", rejected, reason if rejected else "was ACCEPTED (!)")

    sentinel_alive = (await db_manager.run_readwrite(
        f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", (SENTINEL,)))[0][0]
    check("sentinel table survived the injection attempt", sentinel_alive == 1)
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{SENTINEL}"')

    # --- Criterion 5: schema_version increments ---
    print("\n--- 5. schema_version increments across transforms ---")
    await _reset_to_pristine(S_A, tname_a)
    v0 = redis_manager.get_version(S_A)
    await transform_service.apply_transform(S_A, tname_a, TransformDedupe(op="dedupe"))
    v1 = redis_manager.get_version(S_A)
    await transform_service.apply_transform(
        S_A, tname_a, TransformCast(op="cast", column="cost", new_type="DOUBLE"))
    v2 = redis_manager.get_version(S_A)
    check("schema_version strictly increases per transform", v0 < v1 < v2, f"{v0} < {v1} < {v2}")

    # --- Criterion 6: snapshot cap enforced ---
    print(f"\n--- 6. Snapshot cap enforced (cap = {transform_service.SNAPSHOT_CAP}) ---")
    path_c = _write_csv("capped.csv", CSV_PRIMARY)
    tname_c, _ = _table_name_for(S_C, "capped.csv")
    await analyze_and_register_table(S_C, tname_c, path_c, is_primary=True)
    applies = transform_service.SNAPSHOT_CAP + 5
    for _ in range(applies):
        await transform_service.apply_transform(S_C, tname_c, TransformDedupe(op="dedupe"))
    hist = transform_service.get_history(S_C, tname_c)
    n_backups = (await db_manager.run_readwrite(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name LIKE ?",
        (f"backup_{tname_c}_step_%",)))[0][0]
    check(f"history capped at {transform_service.SNAPSHOT_CAP} states after {applies} applies",
          hist["total_steps"] == transform_service.SNAPSHOT_CAP, f"total_steps={hist['total_steps']}")
    check(f"on-disk snapshots capped at {transform_service.SNAPSHOT_CAP}",
          n_backups == transform_service.SNAPSHOT_CAP, f"backup_tables={n_backups}")
    check("can_redo is False at head, can_undo True", hist["can_undo"] and not hist["can_redo"])

    await _teardown()


def http_main():
    """End-to-end leg through the real FastAPI endpoints: proves routing, the
    discriminated-union body, GET /schema reflecting post-transform types, and
    the TransformError -> HTTP 400 mapping."""
    from fastapi.testclient import TestClient
    from main import app

    print("\n--- HTTP end-to-end (real endpoints via TestClient) ---")
    client = TestClient(app)

    r = client.post("/sessions", files={"file": ("primary.csv", CSV_PRIMARY, "text/csv")})
    check("POST /sessions returns 200", r.status_code == 200, f"status={r.status_code}")
    body = r.json()
    sid = body["session_uuid"]
    tname = body["table_name"]
    check("uploaded table has 5 rows", body["row_count"] == 5, f"row_count={body['row_count']}")

    r = client.get(f"/sessions/{sid}/schema")
    rev_type = next(c["type"] for c in r.json()["tables"][0]["columns"] if c["name"] == "revenue")
    check("GET /schema reports revenue as BIGINT before cast", "BIGINT" in rev_type.upper(), rev_type)

    r = client.post(f"/sessions/{sid}/transform", json={"op": "cast", "column": "revenue", "new_type": "DOUBLE"})
    check("POST /transform cast returns 200", r.status_code == 200, f"status={r.status_code}")
    check("transform response carries schema_version >= 1", r.json()["schema_version"] >= 1)

    r = client.get(f"/sessions/{sid}/schema")
    rev_type = next(c["type"] for c in r.json()["tables"][0]["columns"] if c["name"] == "revenue")
    check("GET /schema reflects post-cast revenue type DOUBLE", "DOUBLE" in rev_type.upper(), rev_type)

    r = client.post(f"/sessions/{sid}/transform", json={"op": "dedupe"})
    check("POST /transform dedupe returns row_count 4", r.json()["row_count"] == 4, f"row_count={r.json()['row_count']}")

    r = client.post(f"/sessions/{sid}/undo")
    check("POST /undo reverts dedupe (row_count back to 5)", r.json()["row_count"] == 5, f"row_count={r.json()['row_count']}")

    r = client.get(f"/sessions/{sid}/history")
    h = r.json()
    check("GET /history exposes undo/redo state", h["can_redo"] is True and h["total_steps"] >= 2,
          f"total_steps={h['total_steps']} can_redo={h['can_redo']}")

    r = client.post(f"/sessions/{sid}/transform",
                    json={"op": "calculated_column", "new_column_name": "evil", "formula": f"1); DROP TABLE {tname}; --"})
    check("malicious calculated_column formula -> HTTP 400", r.status_code == 400, f"status={r.status_code}")

    # Clean up the client's randomly-named session so re-runs don't accumulate.
    async def _cleanup_http():
        await _drop_like(f"%{tname}%")
        _redis_cleanup(sid)
    asyncio.run(_cleanup_http())


def main():
    asyncio.run(service_main())
    http_main()
    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED -> {_failures}")
        print("=" * 70)
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    print("=" * 70)


if __name__ == "__main__":
    main()
