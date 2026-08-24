"""TASK-022 proof: the /data endpoint now powers the grid's in-grid tools --
server-side multi-sort, substring search, and whole-table heatmap ranges.

Standalone and idempotent (AP-7): drops its own fixture tables first, so it runs
twice consecutively with identical results. Announces the live Redis backend
(AP-9) -- the endpoint resolves the target table via the schema cache, so this
path really does touch Redis. Must run with the uvicorn backend STOPPED: the
TestClient opens the single-file spencer.db, which holds one write lock.

The fixture is engineered so every assertion has a clean, deterministic target:
score has 3-way ties (multi-sort tiebreak) and one NULL (NULLS LAST), one name
holds a literal '%' (LIKE-escape proof), and categories are low-cardinality
(search hit-count proof). id/score are numeric (ranges) while name/category are
text (excluded from ranges).
"""

import asyncio
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager

client = TestClient(app)

FIXTURE = "gridpower.csv"
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
    """13 rows. score ties: 5.0 x3 (id 4,6,10), 10.5 x3 (0,2,8), 20.0 x2 (1,9),
    99.0 x2 (7,11); id 12 has a NULL score. name 'judy%' carries a literal percent.
    North={0,2,8,12} South={1,3,9} East={4,6,10} West={5,7,11}."""
    rows = [
        (0, "10.5", "Alice", "North"),
        (1, "20.0", "bob", "South"),
        (2, "10.5", "Carol", "North"),
        (3, "30.0", "Dave", "South"),
        (4, "5.0", "eve", "East"),
        (5, "50.0", "Frank", "West"),
        (6, "5.0", "Grace", "East"),
        (7, "99.0", "Heidi", "West"),
        (8, "10.5", "Ivan", "North"),
        (9, "20.0", "judy%", "South"),
        (10, "5.0", "Ken", "East"),
        (11, "99.0", "Laura", "West"),
        (12, "", "Mia", "North"),   # NULL score
    ]
    lines = ["id,score,name,category"]
    lines += [f"{i},{s},{n},{c}" for (i, s, n, c) in rows]
    return "\n".join(lines) + "\n"


async def _drop_fixture_tables():
    rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE ?",
        ("%gridpower%",),
    )
    for (tn,) in rows or []:
        await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{tn}"')


def _ids(resp):
    return [r["id"] for r in resp["rows"]]


def main():
    print("=" * 70)
    print("TASK-022 PROOF -- /data server-side sort + search + heatmap ranges")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    asyncio.run(_drop_fixture_tables())   # idempotency

    r = client.post("/sessions", files={"file": (FIXTURE, _build_csv(), "text/csv")})
    check("POST /sessions -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    sid = r.json()["session_uuid"]

    # --- 0. regression: no sort/no q -> rowid order, all rows -----------------
    print("\n--- 0. Default (no sort/search) still orders by rowid ---")
    d = client.get(f"/sessions/{sid}/data", params={"offset": 0, "limit": 50}).json()
    check("default: 13 rows in ascending rowid order", _ids(d) == list(range(13)), f"ids={_ids(d)}")
    check("default: total == 13", d["total"] == 13, f"total={d['total']}")

    # --- 1. heatmap ranges (offset 0 only, numeric columns only) --------------
    print("\n--- 1. Heatmap ranges: whole-table numeric min/max ---")
    rng = d.get("ranges")
    check("ranges present on first window", isinstance(rng, dict), f"ranges={rng}")
    rng = rng or {}
    check("ranges['id'] == [0, 12]", rng.get("id") == [0.0, 12.0], f"id={rng.get('id')}")
    check("ranges['score'] == [5.0, 99.0] (NULL ignored)", rng.get("score") == [5.0, 99.0], f"score={rng.get('score')}")
    check("text column 'name' NOT in ranges", "name" not in rng, f"keys={list(rng.keys())}")
    check("text column 'category' NOT in ranges", "category" not in rng)
    later = client.get(f"/sessions/{sid}/data", params={"offset": 5, "limit": 50}).json()
    check("ranges omitted on non-first window (offset=5)", later.get("ranges") is None, f"ranges={later.get('ranges')}")

    # --- 2. single-column sort (asc/desc) + NULLS LAST ------------------------
    print("\n--- 2. Single-column sort ---")
    desc = client.get(f"/sessions/{sid}/data", params={"sort": "score:desc", "limit": 50}).json()
    check("sort score:desc -> first row score 99.0", desc["rows"][0]["score"] == 99.0, f"first={desc['rows'][0]}")
    check("sort score:desc -> tie broken by rowid (id 7 before 11)",
          _ids(desc)[:2] == [7, 11], f"first2={_ids(desc)[:2]}")
    asc = client.get(f"/sessions/{sid}/data", params={"sort": "score:asc", "limit": 50}).json()
    check("sort score:asc -> first row score 5.0", asc["rows"][0]["score"] == 5.0, f"first={asc['rows'][0]}")
    check("sort score:asc -> NULL score sorts LAST (id 12)", _ids(asc)[-1] == 12, f"last={_ids(asc)[-1]}")

    # --- 3. multi-sort: category tiebreak proves secondary key applies --------
    print("\n--- 3. Multi-column sort ---")
    multi = client.get(f"/sessions/{sid}/data", params={"sort": "score:asc,id:desc", "limit": 50}).json()
    check("sort score:asc,id:desc -> among score=5.0, id descending (10,6,4)",
          _ids(multi)[:3] == [10, 6, 4], f"first3={_ids(multi)[:3]}")
    check("multi-sort still lands NULL score last (id 12)", _ids(multi)[-1] == 12, f"last={_ids(multi)[-1]}")

    # --- 4. sort validation -> 400 (never interpolated blindly) ---------------
    print("\n--- 4. Sort validation ---")
    bad_col = client.get(f"/sessions/{sid}/data", params={"sort": "nope:asc"})
    check("unknown sort column -> 400", bad_col.status_code == 400, f"status={bad_col.status_code}")
    bad_dir = client.get(f"/sessions/{sid}/data", params={"sort": "score:sideways"})
    check("invalid sort direction -> 400", bad_dir.status_code == 400, f"status={bad_dir.status_code}")

    # --- 5. search: case-insensitive, filters rows AND total ------------------
    print("\n--- 5. Search (substring, case-insensitive) ---")
    north = client.get(f"/sessions/{sid}/data", params={"q": "north", "limit": 50}).json()
    check("q='north' (lowercase) -> 4 North rows (ILIKE)", north["total"] == 4 and len(north["rows"]) == 4,
          f"total={north['total']} n={len(north['rows'])}")
    check("q='north' -> every returned row is category North",
          all(row["category"] == "North" for row in north["rows"]), f"cats={[r['category'] for r in north['rows']]}")

    # --- 6. LIKE-escape: '%' is literal, not a wildcard -----------------------
    print("\n--- 6. LIKE-metacharacter escape ---")
    pct = client.get(f"/sessions/{sid}/data", params={"q": "%", "limit": 50}).json()
    check("q='%' matches only the literal-% value (id 9), NOT all 13 rows",
          pct["total"] == 1 and _ids(pct) == [9], f"total={pct['total']} ids={_ids(pct)}")

    # --- 7. injection-shaped term is inert (parameterized) --------------------
    print("\n--- 7. Search term is a bound parameter ---")
    inj = client.get(f"/sessions/{sid}/data", params={"q": "' OR '1'='1"})
    check("injection-shaped q -> 200 (no SQL error)", inj.status_code == 200, f"status={inj.status_code}")
    check("injection-shaped q -> 0 literal matches", inj.json()["total"] == 0, f"total={inj.json()['total']}")

    # --- 8. search + sort compose --------------------------------------------
    print("\n--- 8. Search + sort together ---")
    combo = client.get(f"/sessions/{sid}/data", params={"q": "south", "sort": "id:desc", "limit": 50}).json()
    check("q='south' + sort id:desc -> South ids 9,3,1", _ids(combo) == [9, 3, 1], f"ids={_ids(combo)}")

    # --- teardown (idempotent re-run) ----------------------------------------
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
