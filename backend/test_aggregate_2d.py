"""TASK-025 (Wave 5) proof: the 2-D aggregate contract.

The Canvas aggregate endpoint gained an optional SECOND grouping dimension -- the
`series` breakdown -- turning a 1-D (keys[] / values[]) result into a
keys x series_keys -> matrix[i][j] pivot, WITHOUT changing the 1-D shape when no
breakdown is set. This drives the new 2-D chart types (heatmap, stacked bar) and the
multi-series bar/line/area renders.

Standalone and idempotent (AP-7): tears down its own fixture first, so it runs twice
consecutively with identical results. Redis-free (aggregation never touches the cache),
but announces the backend per the harness convention (AP-9). Must run with the uvicorn
backend STOPPED: it drives the real single-file spencer.db via db_manager, which holds a
single write lock.

Run from a throwaway CWD so `duckdb.connect("spencer.db")` opens a fresh unlocked DB:
    TMPD=$(mktemp -d) && cd "$TMPD" && python "E:/SPENCER V1/backend/test_aggregate_2d.py"

The fixture is a typed CREATE TABLE with a real DATE column (to prove temporal-dimension
ascending ordering) and an engineered MISSING combination (West x B has no rows) to prove
a hole in the grid pivots to None rather than 0.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
from services import aggregate_service
from models.schemas import AggregateRequest

SRC = "test_agg2d_src"
_failures = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(label)
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


async def _teardown():
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{SRC}"')


async def _seed():
    """Four rows. region x category has one deliberately MISSING cell (West x B):
         region  category  amount  day
         East    A         10      2026-01-02
         East    A         20      2026-01-01   -> East x A sum = 30
         East    B          5      2026-01-02   -> East x B sum = 5
         West    A        100      2026-01-01   -> West x A sum = 100, West x B = (none)
       region sums: West=100, East=35        -> primary keys, value desc: [West, East]
       category sums: A=130, B=5             -> series keys, magnitude desc: [A, B]
       day sums:  2026-01-01=120, 2026-01-02=15  (temporal dimension, ascending)
    """
    await _teardown()
    await db_manager.run_readwrite(
        f'''CREATE TABLE "{SRC}" AS SELECT * FROM (VALUES
            ('East', 'A',  10, DATE '2026-01-02'),
            ('East', 'A',  20, DATE '2026-01-01'),
            ('East', 'B',   5, DATE '2026-01-02'),
            ('West', 'A', 100, DATE '2026-01-01')
        ) AS t(region, category, amount, day)'''
    )


async def service_main():
    print("=" * 70)
    print("TASK-025 PROOF -- 2-D aggregate contract (dimension x series -> matrix)")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    await _seed()

    # --- 1. Core 2-D pivot: region x category, SUM(amount) ------------------------
    print("\n--- 2-D pivot (region x category, sum amount) ---")
    r = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="region", series="category",
                              measure="amount", aggregation="sum")
    )
    print(f"    keys={r['keys']}  series_keys={r['series_keys']}  matrix={r['matrix']}")
    check("dimension echoed", r["dimension"] == "region", r["dimension"])
    check("series echoed", r["series"] == "category", r["series"])
    check("primary keys ordered by value desc [West, East]",
          r["keys"] == ["West", "East"], str(r["keys"]))
    check("series keys ordered by magnitude desc [A, B]",
          r["series_keys"] == ["A", "B"], str(r["series_keys"]))
    # matrix rows follow keys ([West, East]); cols follow series_keys ([A, B]).
    check("matrix shape 2x2", len(r["matrix"]) == 2 and all(len(row) == 2 for row in r["matrix"]),
          str(r["matrix"]))
    check("West x A = 100", r["matrix"][0][0] == 100, str(r["matrix"][0][0]))
    check("MISSING West x B pivots to None (not 0)",
          r["matrix"][0][1] is None, str(r["matrix"][0][1]))
    check("East x A = 30", r["matrix"][1][0] == 30, str(r["matrix"][1][0]))
    check("East x B = 5", r["matrix"][1][1] == 5, str(r["matrix"][1][1]))
    check("values[] is empty in the 2-D shape", r["values"] == [], str(r["values"]))
    check("not truncated (4 rows < limit, 2 series < MAX_SERIES)",
          r["truncated"] is False, str(r["truncated"]))
    check("compiled_sql shows all three passes",
          r["compiled_sql"].count("--") >= 3, str(r["compiled_sql"].count("--")))

    # --- 2. Temporal primary dimension sorts ASCENDING ----------------------------
    print("\n--- temporal dimension (day x region) sorts ascending ---")
    rt = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="day", series="region",
                              measure="amount", aggregation="sum")
    )
    print(f"    keys={rt['keys']}  series_keys={rt['series_keys']}  matrix={rt['matrix']}")
    check("temporal keys ascending [2026-01-01, 2026-01-02]",
          rt["keys"] == ["2026-01-01", "2026-01-02"], str(rt["keys"]))
    check("dates returned as ISO strings (jsonable)",
          all(isinstance(k, str) for k in rt["keys"]), str(rt["keys"]))
    # series (region) magnitude desc: West=100, East=35 -> [West, East]
    check("series keys [West, East]", rt["series_keys"] == ["West", "East"], str(rt["series_keys"]))
    check("2026-01-01 x West = 100", rt["matrix"][0][0] == 100, str(rt["matrix"][0][0]))
    check("MISSING 2026-01-02 x West is None",
          rt["matrix"][1][0] is None, str(rt["matrix"][1][0]))
    check("2026-01-02 x East = 15", rt["matrix"][1][1] == 15, str(rt["matrix"][1][1]))

    # --- 3. Backward-compat: series=None => unchanged 1-D shape -------------------
    print("\n--- 1-D backward-compat (series omitted) ---")
    r1 = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="region", measure="amount", aggregation="sum")
    )
    print(f"    keys={r1['keys']}  values={r1['values']}")
    check("1-D keys [West, East]", r1["keys"] == ["West", "East"], str(r1["keys"]))
    check("1-D values [100, 35]", r1["values"] == [100, 35], str(r1["values"]))
    check("1-D series is None", r1["series"] is None, str(r1["series"]))
    check("1-D series_keys empty", r1["series_keys"] == [], str(r1["series_keys"]))
    check("1-D matrix empty", r1["matrix"] == [], str(r1["matrix"]))

    # --- 4. series == dimension is a no-op (falls through to 1-D) -----------------
    print("\n--- series == dimension is a redundant no-op (1-D) ---")
    rn = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="region", series="region",
                              measure="amount", aggregation="sum")
    )
    check("self-series returns 1-D shape (matrix empty, values set)",
          rn["matrix"] == [] and rn["values"] == [100, 35],
          f"matrix={rn['matrix']} values={rn['values']}")

    # --- 5. Unknown breakdown column -> AggregateError (maps to 400) --------------
    print("\n--- validation: unknown breakdown column ---")
    try:
        await aggregate_service.aggregate(
            SRC, AggregateRequest(dimension="region", series="nope",
                                  measure="amount", aggregation="sum")
        )
        check("unknown series raises AggregateError", False, "no error raised")
    except aggregate_service.AggregateError as e:
        check("unknown series raises AggregateError", True, str(e))

    await _teardown()

    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} FAILURE(S): {_failures}")
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(service_main())
    sys.exit(1 if _failures else 0)
