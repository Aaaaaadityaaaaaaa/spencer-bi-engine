"""TASK-005 proof: Data Cleaning v2 -- new ops, predicate filtering, function
allowlist, and dry-run preview.

Standalone and idempotent (AP-7): tears down its own fixtures first, so it can be
run twice consecutively with identical results. Announces the live Redis backend
(AP-9) -- if that is not `redis`, the cache-touching proof is void.

Covers every TASK-005 acceptance criterion with real, printed output:
  1. each new op on a real table, with compiled DuckDB SQL + real effect
     (drop_column, rename_column, dedupe_subset first/last, string_normalize
      trim/case/replace/null_token, filter_rows keep/remove, impute_null mode
      on BOTH a numeric and a categorical column)
  1b. case variants proven mutually distinct on multi-char words (upper vs lower
     vs capitalize), the full trim->case->replace->null_token chain in one call,
     a multi-column dedupe subset, and the fail-closed guard branches
  2. filter_rows with a malicious predicate rejected; sentinel table survives
  3. function allowlist: non-whitelisted calls (nextval/read_csv_auto/pg_sleep)
     rejected in BOTH formula and predicate; whitelisted funcs still pass
  4. dry-run preview returns the correct row-count delta WITHOUT changing the
     table, adding a history step, or bumping schema_version
  5. undo/redo round-trips across the new ops
  6. real Redis, runnable twice
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
    _table_name_for,
)
from models.schemas import (
    TransformDropColumn,
    TransformRenameColumn,
    TransformDedupeSubset,
    TransformStringNormalize,
    TransformFilterRows,
    TransformImputeNull,
    TransformCalculatedColumn,
)

S_A = "test-t5-a"
SENTINEL = "sentinel_survivor_v2"

# 5 rows. Deliberately messy so each op has a clean, assertable effect:
#  - region: North appears twice  -> dedupe_subset on [region] gives 4 rows
#  - revenue: has <=0 values        -> filter_rows "revenue > 0" gives 3 rows
#  - cost: one null, mode is 20     -> impute_null mode fills the null with 20
#  - grade: leading spaces / mixed case / an "N/A" token -> string_normalize
#  - status: one null, mode active  -> impute_null mode on a CATEGORICAL column
CSV = (
    "region,revenue,cost,grade,status\n"
    'North,100,20,"  a",active\n'
    'North,100,20,"A",active\n'
    'South,200,,"b",active\n'
    'West,-5,20,"  a",inactive\n'
    'East,0,40,"N/A",\n'
)

# Multi-character mixed-case words, so upper/lower/capitalize are mutually
# DISTINGUISHABLE (single-char inputs can't tell them apart).
CSV_STR = (
    "word\n"
    "hELLo\n"
    "WORLD\n"
    "fOO\n"
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
    await _drop_like("%test_t5%")
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{SENTINEL}"')
    _redis_cleanup(S_A)


def _write_csv(name, body):
    os.makedirs("uploads/_tasktest", exist_ok=True)
    path = f"uploads/_tasktest/{name}"
    with open(path, "w", newline="") as f:
        f.write(body)
    return path


async def _rowcount(tbl):
    return (await db_manager.run_readwrite(f'SELECT COUNT(*) FROM "{tbl}"'))[0][0]


async def _cols(tbl):
    info = await db_manager.run_readwrite(f'PRAGMA table_info("{tbl}")')
    return [row[1] for row in info]


async def _count_where(tbl, cond):
    return (await db_manager.run_readwrite(f'SELECT COUNT(*) FROM "{tbl}" WHERE {cond}'))[0][0]


async def _cell(tbl, col, where_col, where_val):
    res = await db_manager.run_readwrite(
        f'SELECT "{col}" FROM "{tbl}" WHERE "{where_col}" = ?', (where_val,))
    return res[0][0] if res else None


async def _reset_to_pristine(session, tbl):
    while transform_service.get_history(session, tbl)["can_undo"]:
        await transform_service.undo(session, tbl)


async def _apply(session, tbl, param, reset=True):
    """Apply from pristine, returning the resulting row count."""
    if reset:
        await _reset_to_pristine(session, tbl)
    _, _, rc = await transform_service.apply_transform(session, tbl, param)
    return rc


def _compiled(tbl, cols, param):
    return transform_service._compile_op(tbl, cols, param)


async def service_main():
    print("=" * 70)
    print("TASK-005 PROOF -- data cleaning v2 (new ops, predicate, allowlist, preview)")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    await _teardown()

    path = _write_csv("v2.csv", CSV)
    tname, _ = _table_name_for(S_A, "v2.csv")
    await analyze_and_register_table(S_A, tname, path, is_primary=True)
    base_rows = await _rowcount(tname)
    print(f"\nRegistered {tname} with {base_rows} rows.")
    cols = await transform_service._columns_of(tname)

    # ------------------------------------------------------------------ #
    print("\n--- 1. Each new op: compiled DuckDB SQL + real effect ---")

    # drop_column
    p = TransformDropColumn(op="drop_column", column="cost")
    print("\n[drop_column cost] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    await _apply(S_A, tname, p)
    after_cols = await _cols(tname)
    check("drop_column removes 'cost'", "cost" not in after_cols, f"cols={after_cols}")
    check("drop_column keeps the other 4 columns", len(after_cols) == 4)

    # rename_column
    p = TransformRenameColumn(op="rename_column", column="revenue", new_name="sales")
    print("\n[rename_column revenue->sales] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    await _apply(S_A, tname, p)
    after_cols = await _cols(tname)
    check("rename_column adds 'sales', drops 'revenue'",
          "sales" in after_cols and "revenue" not in after_cols, f"cols={after_cols}")

    # rename collision rejected
    collided = False
    try:
        await _apply(S_A, tname, TransformRenameColumn(op="rename_column", column="revenue", new_name="cost"))
    except transform_service.TransformError as e:
        collided = True; reason = str(e)
    check("rename_column collision with existing name rejected", collided,
          reason if collided else "was ACCEPTED (!)")

    # dedupe_subset keep=first
    p = TransformDedupeSubset(op="dedupe_subset", columns=["region"], keep="first")
    print("\n[dedupe_subset on region, keep=first] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    rc = await _apply(S_A, tname, p)
    distinct_regions = (await db_manager.run_readwrite(
        f'SELECT COUNT(DISTINCT region) FROM "{tname}"'))[0][0]
    check("dedupe_subset[region] collapses North's dup (5 -> 4)", rc == 4, f"row_count={rc}")
    check("dedupe_subset preserves all 4 distinct regions", distinct_regions == 4)

    # dedupe_subset keep=last (row count identical; keep differs only in which non-key value survives)
    rc = await _apply(S_A, tname, TransformDedupeSubset(op="dedupe_subset", columns=["region"], keep="last"))
    check("dedupe_subset keep=last also yields 4 rows", rc == 4, f"row_count={rc}")

    # string_normalize: trim + capitalize
    p = TransformStringNormalize(op="string_normalize", column="grade", trim=True, case="capitalize")
    print("\n[string_normalize grade trim+capitalize] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    await _apply(S_A, tname, p)
    n_A = await _count_where(tname, "grade = 'A'")
    n_B = await _count_where(tname, "grade = 'B'")
    check("string_normalize trim+capitalize: '  a'/'A' -> 'A' (3 rows)", n_A == 3, f"count(A)={n_A}")
    check("string_normalize trim+capitalize: 'b' -> 'B' (1 row)", n_B == 1, f"count(B)={n_B}")

    # string_normalize: null_token maps 'N/A' -> NULL
    await _apply(S_A, tname, TransformStringNormalize(op="string_normalize", column="grade", null_token="N/A"))
    n_null = await _count_where(tname, "grade IS NULL")
    check("string_normalize null_token 'N/A' -> NULL (1 row)", n_null == 1, f"null grades={n_null}")

    # string_normalize: find/replace
    await _apply(S_A, tname, TransformStringNormalize(op="string_normalize", column="grade", find="b", replace="beta"))
    n_beta = await _count_where(tname, "grade = 'beta'")
    check("string_normalize find 'b' replace 'beta' (1 row)", n_beta == 1, f"count(beta)={n_beta}")

    # string_normalize on a non-text column rejected
    rejected = False
    try:
        await _apply(S_A, tname, TransformStringNormalize(op="string_normalize", column="revenue", trim=True))
    except transform_service.TransformError as e:
        rejected = True; reason = str(e)
    check("string_normalize on numeric column rejected", rejected, reason if rejected else "ACCEPTED (!)")

    # filter_rows keep
    p = TransformFilterRows(op="filter_rows", predicate="revenue > 0", action="keep")
    print("\n[filter_rows keep 'revenue > 0'] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    rc = await _apply(S_A, tname, p)
    check("filter_rows keep 'revenue > 0' drops the <=0 rows (5 -> 3)", rc == 3, f"row_count={rc}")

    # filter_rows remove
    rc = await _apply(S_A, tname, TransformFilterRows(op="filter_rows", predicate="region = 'North'", action="remove"))
    check("filter_rows remove region='North' drops both North rows (5 -> 3)", rc == 3, f"row_count={rc}")

    # impute_null mode on a NUMERIC column (cost: [20,20,null,20,40] -> mode 20)
    p = TransformImputeNull(op="impute_null", column="cost", strategy="mode")
    print("\n[impute_null cost=mode] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    await _apply(S_A, tname, p)
    south_cost = await _cell(tname, "cost", "region", "South")
    cost_nulls = await _count_where(tname, "cost IS NULL")
    check("impute mode fills South's null cost with the mode (20)", south_cost == 20, f"cost={south_cost}")
    check("impute mode leaves no null cost", cost_nulls == 0, f"null_cost={cost_nulls}")

    # impute_null mode on a CATEGORICAL column (status: 3x active,1x inactive,1x null -> active)
    await _apply(S_A, tname, TransformImputeNull(op="impute_null", column="status", strategy="mode"))
    east_status = await _cell(tname, "status", "region", "East")
    status_nulls = await _count_where(tname, "status IS NULL")
    check("impute mode fills East's null status with the categorical mode ('active')",
          east_status == "active", f"status={east_status}")
    check("impute mode leaves no null status", status_nulls == 0, f"null_status={status_nulls}")

    # ------------------------------------------------------------------ #
    print("\n--- 1b. case variants (upper/lower/capitalize), compose chain, "
          "multi-column dedupe, guard branches ---")

    # A separate fixture of multi-char mixed-case words, so upper/lower/capitalize
    # produce mutually DISTINCT results (the single-char grades above cannot tell
    # them apart -- 'a'.upper() == 'a'.capitalize()).
    path_w = _write_csv("words.csv", CSV_STR)
    tname_w, _ = _table_name_for(S_A, "words.csv")
    await analyze_and_register_table(S_A, tname_w, path_w, is_primary=False)
    cols_w = await transform_service._columns_of(tname_w)
    check("words fixture registered with 3 rows", await _rowcount(tname_w) == 3)

    # case=upper : hELLo/WORLD/fOO -> HELLO/WORLD/FOO
    p = TransformStringNormalize(op="string_normalize", column="word", case="upper")
    print("\n[string_normalize word case=upper] compiled SQL:")
    print("    " + _compiled(tname_w, cols_w, p).replace("\n", "\n    "))
    await _apply(S_A, tname_w, p)
    check("case=upper: 'hELLo' -> 'HELLO'", await _count_where(tname_w, "word = 'HELLO'") == 1)
    check("case=upper: 'fOO' -> 'FOO'", await _count_where(tname_w, "word = 'FOO'") == 1)
    check("case=upper yields NO 'Hello' (distinct from capitalize)",
          await _count_where(tname_w, "word = 'Hello'") == 0)

    # case=lower : -> hello/world/foo
    await _apply(S_A, tname_w, TransformStringNormalize(op="string_normalize", column="word", case="lower"))
    check("case=lower: 'WORLD' -> 'world'", await _count_where(tname_w, "word = 'world'") == 1)
    check("case=lower: 'hELLo' -> 'hello'", await _count_where(tname_w, "word = 'hello'") == 1)

    # case=capitalize : -> Hello/World/Foo (first char upper, rest lower)
    await _apply(S_A, tname_w, TransformStringNormalize(op="string_normalize", column="word", case="capitalize"))
    check("case=capitalize: 'hELLo' -> 'Hello'", await _count_where(tname_w, "word = 'Hello'") == 1)
    check("case=capitalize: 'WORLD' -> 'World'", await _count_where(tname_w, "word = 'World'") == 1)
    check("case=capitalize: 'fOO' -> 'Foo'", await _count_where(tname_w, "word = 'Foo'") == 1)

    # compose ALL steps in ONE call, proving order trim -> case -> replace -> null_token:
    #   'WORLD' -> (trim) WORLD -> (lower) world -> (replace o->0) w0rld -> (null_token) NULL
    #   'hELLo' -> hELLo -> hello -> hell0
    #   'fOO'   -> fOO   -> foo   -> f00
    p = TransformStringNormalize(op="string_normalize", column="word",
                                 trim=True, case="lower", find="o", replace="0", null_token="w0rld")
    print("\n[string_normalize word trim+lower+replace(o->0)+null_token(w0rld)] compiled SQL:")
    print("    " + _compiled(tname_w, cols_w, p).replace("\n", "\n    "))
    await _apply(S_A, tname_w, p)
    check("compose: 'WORLD' -> NULL via lower->replace->null_token (1 null)",
          await _count_where(tname_w, "word IS NULL") == 1)
    check("compose: 'hELLo' -> 'hell0' (case applied before replace)",
          await _count_where(tname_w, "word = 'hell0'") == 1)
    check("compose: 'fOO' -> 'f00' (both o's replaced)",
          await _count_where(tname_w, "word = 'f00'") == 1)

    # multi-column dedupe_subset: on [region, grade] the two North rows are NOT
    # merged (their grades differ: '  a' vs 'A'), so it stays 5 rows -- proving the
    # subset key considers BOTH columns, unlike single-column [region] (-> 4 above).
    p = TransformDedupeSubset(op="dedupe_subset", columns=["region", "grade"], keep="first")
    print("\n[dedupe_subset on [region, grade]] compiled SQL:")
    print("    " + _compiled(tname, cols, p).replace("\n", "\n    "))
    rc = await _apply(S_A, tname, p)
    check("dedupe_subset[region,grade] keeps all 5 (North rows differ on grade)",
          rc == 5, f"row_count={rc}")

    # guard branches all raise TransformError (fail-closed, not a raw engine crash)
    guards = {
        "drop_column unknown column": TransformDropColumn(op="drop_column", column="does_not_exist"),
        "dedupe_subset unknown column": TransformDedupeSubset(op="dedupe_subset", columns=["nope"]),
        "string_normalize with no operation": TransformStringNormalize(op="string_normalize", column="grade"),
    }
    for label, gparam in guards.items():
        rejected = False
        try:
            await _apply(S_A, tname, gparam)
        except transform_service.TransformError as e:
            rejected = True; reason = str(e)
        check(f"guard rejects: {label}", rejected, reason if rejected else "ACCEPTED (!)")

    # ------------------------------------------------------------------ #
    print("\n--- 2. Malicious filter_rows predicate rejected; sentinel survives ---")
    await db_manager.run_readwrite(f'CREATE TABLE "{SENTINEL}" (id INTEGER)')
    await db_manager.run_readwrite(f'INSERT INTO "{SENTINEL}" VALUES (1)')
    attacks = {
        "statement injection": f"1); DROP TABLE {SENTINEL}; --",
        "scalar subquery": "revenue > (SELECT max(revenue) FROM information_schema.tables)",
        "unknown column": "nonexistent_col > 0",
        "stacked statement": "revenue > 0; DROP TABLE x",
    }
    for label, pred in attacks.items():
        rejected = False
        try:
            await _apply(S_A, tname, TransformFilterRows(op="filter_rows", predicate=pred, action="keep"))
        except transform_service.TransformError as e:
            rejected = True; reason = str(e)
        check(f"filter_rows rejected: {label}", rejected, reason if rejected else "ACCEPTED (!)")
    sentinel_alive = (await db_manager.run_readwrite(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", (SENTINEL,)))[0][0]
    check("sentinel table survived the predicate injection", sentinel_alive == 1)
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{SENTINEL}"')

    # ------------------------------------------------------------------ #
    print("\n--- 3. Function allowlist (closes ADR-014 residual) ---")
    # Non-whitelisted calls rejected in a calculated_column FORMULA...
    formula_attacks = {
        "nextval() (sequence mutation)": "revenue + nextval('s')",
        "read_csv_auto() (file I/O)": "length(read_csv_auto('x.csv'))",
    }
    for label, formula in formula_attacks.items():
        rejected = False
        try:
            await _apply(S_A, tname, TransformCalculatedColumn(op="calculated_column", new_column_name="evil", formula=formula))
        except transform_service.TransformError as e:
            rejected = True; reason = str(e)
        check(f"formula rejects non-whitelisted {label}", rejected, reason if rejected else "ACCEPTED (!)")

    # ...and in a filter_rows PREDICATE (same validator).
    rejected = False
    try:
        await _apply(S_A, tname, TransformFilterRows(op="filter_rows", predicate="pg_sleep(5) OR revenue > 0"))
    except transform_service.TransformError as e:
        rejected = True; reason = str(e)
    check("predicate rejects non-whitelisted pg_sleep()", rejected, reason if rejected else "ACCEPTED (!)")

    # Whitelisted arithmetic/string funcs still pass (formula) -- South is unique.
    await _apply(S_A, tname, TransformCalculatedColumn(
        op="calculated_column", new_column_name="metric", formula="abs(revenue) + length(grade)"))
    south_metric = await _cell(tname, "metric", "region", "South")
    check("whitelisted abs()+length() accepted and correct (South: |200|+len('b')=201)",
          south_metric == 201, f"metric={south_metric}")

    # Whitelisted func in a predicate still passes.
    rc = await _apply(S_A, tname, TransformFilterRows(op="filter_rows", predicate="round(revenue, 1) > 0"))
    check("whitelisted round() in predicate accepted (3 rows kept)", rc == 3, f"row_count={rc}")

    # ------------------------------------------------------------------ #
    print("\n--- 4. Dry-run preview: reports delta WITHOUT mutating anything ---")
    await _reset_to_pristine(S_A, tname)
    rows_before = await _rowcount(tname)
    hist_before = transform_service.get_history(S_A, tname)["total_steps"]
    ver_before = redis_manager.get_version(S_A)

    prev = await transform_service.preview_transform(
        S_A, tname, TransformFilterRows(op="filter_rows", predicate="revenue > 0"))
    print(f"    preview(filter revenue>0): before={prev['row_count_before']} "
          f"after={prev['row_count_after']} delta={prev['row_count_delta']}")
    print(f"    preview compiled_sql: {prev['compiled_sql']}")
    print(f"    preview sample (first row): {prev['sample'][0] if prev['sample'] else None}")
    check("preview reports before=5", prev["row_count_before"] == 5, f"{prev['row_count_before']}")
    check("preview reports after=3", prev["row_count_after"] == 3, f"{prev['row_count_after']}")
    check("preview reports delta=-2", prev["row_count_delta"] == -2, f"{prev['row_count_delta']}")

    rows_after = await _rowcount(tname)
    hist_after = transform_service.get_history(S_A, tname)["total_steps"]
    ver_after = redis_manager.get_version(S_A)
    check("preview did NOT change the table row count", rows_before == rows_after, f"{rows_before}->{rows_after}")
    check("preview did NOT add a history step", hist_before == hist_after, f"{hist_before}->{hist_after}")
    check("preview did NOT bump schema_version", ver_before == ver_after, f"{ver_before}->{ver_after}")

    # preview of drop_column shows the post-op schema without touching the live table
    prev = await transform_service.preview_transform(S_A, tname, TransformDropColumn(op="drop_column", column="cost"))
    preview_cols = [c["name"] for c in prev["columns"]]
    live_cols = await _cols(tname)
    check("preview(drop_column) shows schema minus 'cost'", "cost" not in preview_cols, f"{preview_cols}")
    check("live table still HAS 'cost' after preview", "cost" in live_cols, f"{live_cols}")

    # a malicious predicate is rejected at PREVIEW time too (same validator)
    prev_rejected = False
    try:
        await transform_service.preview_transform(
            S_A, tname, TransformFilterRows(op="filter_rows", predicate="revenue + nextval('s') > 0"))
    except transform_service.TransformError:
        prev_rejected = True
    check("preview rejects a non-whitelisted function too", prev_rejected)

    # ------------------------------------------------------------------ #
    print("\n--- 5. Undo/redo round-trips across the new ops ---")
    await _reset_to_pristine(S_A, tname)
    # filter (5->3), then undo restores 5, redo re-applies 3
    await transform_service.apply_transform(S_A, tname, TransformFilterRows(op="filter_rows", predicate="revenue > 0"))
    check("after filter_rows: 3 rows", await _rowcount(tname) == 3)
    _, _, rc = await transform_service.undo(S_A, tname)
    check("undo filter_rows restores 5 rows", rc == 5, f"row_count={rc}")
    _, _, rc = await transform_service.redo(S_A, tname)
    check("redo filter_rows re-applies (3 rows)", rc == 3, f"row_count={rc}")

    # drop_column then undo restores the column
    await _reset_to_pristine(S_A, tname)
    await transform_service.apply_transform(S_A, tname, TransformDropColumn(op="drop_column", column="status"))
    check("after drop_column: 'status' gone", "status" not in await _cols(tname))
    await transform_service.undo(S_A, tname)
    check("undo drop_column restores 'status'", "status" in await _cols(tname))

    await _teardown()


def http_main():
    """End-to-end leg through the real FastAPI endpoints: the new preview endpoint,
    a new op via the discriminated-union body, and TransformError -> HTTP 400."""
    from fastapi.testclient import TestClient
    from main import app

    print("\n--- HTTP end-to-end (real endpoints via TestClient) ---")
    client = TestClient(app)

    r = client.post("/sessions", files={"file": ("v2.csv", CSV, "text/csv")})
    check("POST /sessions returns 200", r.status_code == 200, f"status={r.status_code}")
    body = r.json()
    sid = body["session_uuid"]
    tname = body["table_name"]
    check("uploaded table has 5 rows", body["row_count"] == 5, f"row_count={body['row_count']}")

    # preview endpoint: reports delta, does not mutate
    r = client.post(f"/sessions/{sid}/transform/preview", json={"op": "filter_rows", "predicate": "revenue > 0"})
    check("POST /transform/preview returns 200", r.status_code == 200, f"status={r.status_code}")
    pv = r.json()
    check("preview endpoint reports delta -2", pv["row_count_delta"] == -2, f"delta={pv['row_count_delta']}")

    r = client.get(f"/sessions/{sid}/history")
    check("preview added no history step", r.json()["total_steps"] == 0, f"total_steps={r.json()['total_steps']}")

    # real new op via endpoint
    r = client.post(f"/sessions/{sid}/transform", json={"op": "filter_rows", "predicate": "revenue > 0"})
    check("POST /transform filter_rows returns row_count 3", r.json()["row_count"] == 3, f"row_count={r.json()['row_count']}")

    r = client.post(f"/sessions/{sid}/transform", json={"op": "drop_column", "column": "cost"})
    check("POST /transform drop_column returns 200", r.status_code == 200, f"status={r.status_code}")

    # malicious predicate -> 400 via endpoint
    r = client.post(f"/sessions/{sid}/transform", json={"op": "filter_rows", "predicate": f"1); DROP TABLE {tname}; --"})
    check("malicious predicate -> HTTP 400", r.status_code == 400, f"status={r.status_code}")

    # non-whitelisted function -> 400 via endpoint
    r = client.post(f"/sessions/{sid}/transform", json={"op": "calculated_column", "new_column_name": "x", "formula": "nextval('s')"})
    check("non-whitelisted function -> HTTP 400", r.status_code == 400, f"status={r.status_code}")

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
