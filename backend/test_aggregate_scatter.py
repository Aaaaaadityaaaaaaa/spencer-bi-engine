"""Wave 5 proof: the scatter (raw point cloud) aggregate contract.

When `AggregateRequest.measure_y` is set, `aggregate_service.aggregate` returns RAW
(x, y) POINTS -- a scatter -- instead of a grouped aggregate. `dimension`, if set, is an
optional colour/group column; `aggregation` is ignored. This drives the new 'scatter'
chart type in ChartTile.

Standalone, idempotent (AP-7) and Redis-free, but announces the backend (AP-9). Must run
with the uvicorn backend STOPPED (it drives the single-file spencer.db via db_manager).

Run from a throwaway CWD so a fresh unlocked spencer.db opens:
    TMPD=$(mktemp -d) && cd "$TMPD" && python "E:/SPENCER V1/backend/test_aggregate_scatter.py"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
from services import aggregate_service
from models.schemas import AggregateRequest

SRC = "test_agg_scatter_src"
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
    await _teardown()
    # x, y are numeric measures; grp is a categorical colour column.
    await db_manager.run_readwrite(
        f'''CREATE TABLE "{SRC}" AS SELECT * FROM (VALUES
            (1.0, 2.0, 'A'),
            (3.0, 4.0, 'A'),
            (5.0, 6.0, 'B'),
            (7.0, 8.0, 'B'),
            (9.0, 10.0, 'A')
        ) AS t(x, y, grp)'''
    )


async def service_main():
    print("=" * 70)
    print("WAVE 5 PROOF -- scatter (raw point cloud) aggregate contract")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    await _seed()

    # --- 1. Basic scatter: x vs y, no colour group --------------------------------
    print("\n--- scatter x vs y (no group) ---")
    r = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension=None, measure="x", aggregation="sum", measure_y="y")
    )
    print(f"    points={r['points']}")
    check("keys empty in scatter shape", r["keys"] == [], str(r["keys"]))
    check("values empty in scatter shape", r["values"] == [], str(r["values"]))
    check("matrix empty in scatter shape", r["matrix"] == [], str(r["matrix"]))
    check("aggregation echoed as 'raw'", r["aggregation"] == "raw", r["aggregation"])
    check("measure echoed", r["measure"] == "x", r["measure"])
    check("5 points returned", (r["points"] or []).__len__() == 5, str(len(r["points"] or [])))
    first = (r["points"] or [])[0]
    check("point shape {x, y}", set(first.keys()) == {"x", "y"}, str(first))
    check("first point x=9.0 (order by y desc)", first["x"] == 9.0, str(first))
    check("first point y=10.0", first["y"] == 10.0, str(first))
    check("last point y=2.0 (order by y desc)", (r["points"] or [])[-1]["y"] == 2.0, str((r["points"] or [])[-1]))

    # --- 2. Colour group: dimension becomes the group column ----------------------
    print("\n--- scatter x vs y coloured by grp ---")
    rg = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="grp", measure="x", aggregation="avg", measure_y="y")
    )
    pts = rg["points"] or []
    check("points carry a 'group' key", all("group" in p for p in pts), str(pts[0] if pts else {}))
    groups = {p["group"] for p in pts}
    check("both groups present (A, B)", groups == {"A", "B"}, str(groups))
    check("dimension echoed", rg["dimension"] == "grp", rg["dimension"])

    # --- 3. top_points cap --------------------------------------------------------
    print("\n--- scatter top_points cap ---")
    rc = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension=None, measure="x", aggregation="sum", measure_y="y", top_points=2)
    )
    check("capped to 2 points", (rc["points"] or []).__len__() == 2, str(len(rc["points"] or [])))
    check("truncated flag set", rc["truncated"] is True, str(rc["truncated"]))

    # --- 4. Validation: non-numeric measure / measure_y -> AggregateError ---------
    print("\n--- validation: numeric measures required ---")
    for where in ("measure", "measure_y"):
        req = AggregateRequest(dimension=None, measure="x", aggregation="sum", measure_y="y")
        if where == "measure":
            req.measure = "grp"  # non-numeric X
        else:
            req.measure_y = "grp"  # non-numeric Y
        try:
            await aggregate_service.aggregate(SRC, req)
            check(f"non-numeric {where} raises AggregateError", False, "no error raised")
        except aggregate_service.AggregateError as e:
            check(f"non-numeric {where} raises AggregateError", True, str(e))

    # --- 5. validation: missing column -------------------------------------------
    print("\n--- validation: unknown column ---")
    try:
        await aggregate_service.aggregate(
            SRC, AggregateRequest(dimension=None, measure="missing", aggregation="sum", measure_y="y")
        )
        check("unknown measure raises AggregateError", False, "no error raised")
    except aggregate_service.AggregateError as e:
        check("unknown measure raises AggregateError", True, str(e))

    # --- 6. Box-plot mode --------------------------------------------------------
    print("\n--- box plot (group x by grp) ---")
    rb = await aggregate_service.aggregate(
        SRC, AggregateRequest(dimension="grp", measure="x", aggregation="sum", box=True)
    )
    boxes = rb["boxes"] or []
    print(f"    boxes={boxes}")
    check("keys empty in box shape", rb["keys"] == [], str(rb["keys"]))
    check("values empty in box shape", rb["values"] == [], str(rb["values"]))
    check("aggregation echoed as 'box'", rb["aggregation"] == "box", rb["aggregation"])
    check("2 boxes (A, B)", len(boxes) == 2, str(len(boxes)))
    check("box keys are A and B", {b["key"] for b in boxes} == {"A", "B"}, str({b["key"] for b in boxes}))
    for b in boxes:
        ok = (
            "min" in b and "q1" in b and "median" in b and "q3" in b and "max" in b
            and (b["min"] is None or (b["min"] <= b["q1"] <= b["median"] <= b["q3"] <= b["max"]))
        )
        check(f"box for {b['key']} has ordered stats", ok, str(b))

    # --- 7. Box validation: needs a category dimension ---------------------------
    print("\n--- validation: box needs a category dimension ---")
    try:
        await aggregate_service.aggregate(
            SRC, AggregateRequest(dimension=None, measure="x", aggregation="sum", box=True)
        )
        check("box without dimension raises AggregateError", False, "no error raised")
    except aggregate_service.AggregateError as e:
        check("box without dimension raises AggregateError", True, str(e))

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
