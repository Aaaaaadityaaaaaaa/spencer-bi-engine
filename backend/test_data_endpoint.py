"""TASK-006 proof: the paginated /data endpoint for the virtualized grid.

Standalone and idempotent (AP-7): drops its own fixture tables first, so it runs
twice consecutively with identical results. Announces the live Redis backend
(AP-9) -- if that is not `redis`, the proof is void (the endpoint resolves the
target table via the schema cache, so this path really does touch Redis).

Covers every backend acceptance criterion with real, printed output:
  1. windowed read: offset/limit returns the right rows + envelope fields
  2. pagination correctness: 30-row windows cover all 100 rows exactly once, in
     ascending order (proves ORDER BY rowid gives stable, disjoint windows)
  3. clamp/edge: limit clamped to [1,1000]; negatives floored; offset past end
     -> empty window
  4. table resolution: explicit name ok; unknown name -> 404; empty session -> 404
  5. JSON coercion: a DATE column serializes to an ISO string; a NULL -> null; a
     special-character column header ("amount ($)") round-trips as a dict key
"""

import asyncio
import os
import sys
import shutil
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager

client = TestClient(app)

FIXTURE = "griddata.csv"   # -> internal table t_{uuid}_griddata
N_ROWS = 100

_failures = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(label)
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


def _build_csv():
    """100 rows, deliberately shaped so each assertion has a clean target:
      - id 0..99      : stable unique key, proves window coverage/order
      - event_date    : a real DATE column, proves DATE -> ISO-string coercion
      - "amount ($)"  : float with a NULL every 10th row (special-char header + null)
      - category      : low-cardinality text
    """
    base = datetime.date(2024, 1, 1)
    cats = ["North", "South", "East", "West"]
    lines = ["id,event_date,amount ($),category"]
    for i in range(N_ROWS):
        d = base + datetime.timedelta(days=i)
        amount = "" if i % 10 == 0 else f"{i * 1.5:.2f}"
        lines.append(f"{i},{d.isoformat()},{amount},{cats[i % 4]}")
    return "\n".join(lines) + "\n"


async def _drop_fixture_tables():
    rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE ?",
        ("%griddata%",),
    )
    for (tn,) in rows or []:
        await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{tn}"')


def main():
    print("=" * 70)
    print("TASK-006 PROOF -- paginated /data endpoint (virtualized grid)")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    asyncio.run(_drop_fixture_tables())   # idempotency: clear prior-run fixtures

    csv = _build_csv()
    r = client.post("/sessions", files={"file": (FIXTURE, csv, "text/csv")})
    check("POST /sessions -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    body = r.json()
    sid = body["session_uuid"]
    table_name = body["table_name"]
    check(f"uploaded table has {N_ROWS} rows", body["row_count"] == N_ROWS, f"row_count={body['row_count']}")

    # --- 1. windowed read + envelope -------------------------------------
    print("\n--- 1. Windowed read: offset/limit + envelope ---")
    d = client.get(f"/sessions/{sid}/data", params={"offset": 0, "limit": 30}).json()
    print(f"    envelope: total={d['total']} offset={d['offset']} limit={d['limit']} "
          f"rows={len(d['rows'])} cols={[c['name'] for c in d['columns']]}")
    check("total == 100", d["total"] == N_ROWS, f"total={d['total']}")
    check("offset echoed == 0", d["offset"] == 0)
    check("limit echoed == 30", d["limit"] == 30)
    check("returned exactly 30 rows", len(d["rows"]) == 30, f"n={len(d['rows'])}")
    colnames = [c["name"] for c in d["columns"]]
    check("columns preserved in order [id, event_date, 'amount ($)', category]",
          colnames == ["id", "event_date", "amount ($)", "category"], f"cols={colnames}")

    # --- 2. pagination correctness ---------------------------------------
    print("\n--- 2. Pagination correctness: stable, disjoint, complete windows ---")
    seen = []
    for off in range(0, N_ROWS, 30):
        w = client.get(f"/sessions/{sid}/data", params={"offset": off, "limit": 30}).json()
        seen.extend(row["id"] for row in w["rows"])
    print(f"    concatenated {len(seen)} ids across windows (30+30+30+10)")
    check("windows cover all 100 ids exactly once, ascending (ORDER BY rowid)",
          seen == list(range(N_ROWS)), f"first10={seen[:10]} len={len(seen)}")
    last = client.get(f"/sessions/{sid}/data", params={"offset": 90, "limit": 30}).json()
    check("final window (offset=90) has the last 10 rows", len(last["rows"]) == 10, f"n={len(last['rows'])}")

    # --- 3. clamp + edge -------------------------------------------------
    print("\n--- 3. Clamp + edge cases ---")
    over = client.get(f"/sessions/{sid}/data", params={"offset": 0, "limit": 99999}).json()
    check("limit clamped to 1000 in echoed envelope", over["limit"] == 1000, f"limit={over['limit']}")
    check("all 100 rows returned (100 < clamp)", len(over["rows"]) == N_ROWS, f"n={len(over['rows'])}")
    zero = client.get(f"/sessions/{sid}/data", params={"offset": 0, "limit": 0}).json()
    check("limit=0 floored to 1", zero["limit"] == 1 and len(zero["rows"]) == 1,
          f"limit={zero['limit']} n={len(zero['rows'])}")
    neg = client.get(f"/sessions/{sid}/data", params={"offset": -5, "limit": -5}).json()
    check("negative offset/limit clamped (offset=0, limit=1)",
          neg["offset"] == 0 and neg["limit"] == 1, f"offset={neg['offset']} limit={neg['limit']}")
    past = client.get(f"/sessions/{sid}/data", params={"offset": 100000, "limit": 30}).json()
    check("offset past end -> empty window, total still 100",
          past["rows"] == [] and past["total"] == N_ROWS, f"rows={len(past['rows'])} total={past['total']}")

    # --- 4. table resolution + 404s --------------------------------------
    print("\n--- 4. Table resolution + 404s ---")
    named = client.get(f"/sessions/{sid}/data", params={"table_name": table_name, "limit": 5})
    check("explicit valid table_name -> 200, same table",
          named.status_code == 200 and named.json()["total"] == N_ROWS, f"status={named.status_code}")
    unknown = client.get(f"/sessions/{sid}/data", params={"table_name": "does_not_exist"})
    check("unknown table_name -> 404", unknown.status_code == 404, f"status={unknown.status_code}")
    no_session = client.get("/sessions/00000000-0000-0000-0000-000000000000/data")
    check("session with no tables -> 404", no_session.status_code == 404, f"status={no_session.status_code}")

    # --- 5. JSON coercion ------------------------------------------------
    print("\n--- 5. JSON coercion (DATE, NULL, special-char header) ---")
    first = client.get(f"/sessions/{sid}/data", params={"offset": 0, "limit": 1}).json()
    row0 = first["rows"][0]
    print(f"    row0 = {row0}")
    check("id 0 is the first row (rowid order)", row0["id"] == 0, f"id={row0['id']}")
    check("DATE column serialized as ISO string '2024-01-01'",
          isinstance(row0["event_date"], str) and row0["event_date"] == "2024-01-01",
          f"event_date={row0['event_date']!r}")
    check("NULL 'amount ($)' -> JSON null", row0["amount ($)"] is None, f"amount={row0['amount ($)']!r}")
    check("special-character column header round-trips as a dict key", "amount ($)" in row0)
    ev_type = next(c["type"] for c in first["columns"] if c["name"] == "event_date")
    check("event_date column typed DATE", ev_type == "DATE", f"type={ev_type}")

    # --- teardown (idempotent re-run) ------------------------------------
    asyncio.run(_drop_fixture_tables())
    redis_manager.client.delete(f"schema:{sid}")
    redis_manager.client.delete(f"schema_version:{sid}")
    shutil.rmtree(f"uploads/{sid}", ignore_errors=True)

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
