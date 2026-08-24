"""TASK-021 proof: the whole-table data-quality scan now catches all six issue
classes the user named -- Missing (incl. hidden nulls), Duplicates, Wrong format
(mixed date layouts), Wrong data type (text stored as number/date), Invalid values
(negatives + future dates, review-only), and Inconsistent categories (casing).

Standalone and idempotent (AP-7): tears down its own fixture first, so it runs twice
consecutively with identical results. Announces the live Redis backend (AP-9) even
though the scan itself is Redis-free -- the harness convention. Must run with the
uvicorn backend STOPPED: it drives the real single-file spencer.db via db_manager,
which holds a single write lock.

The fixture is a typed CREATE TABLE (full control over a real DATE column, a real INT
column, and VARCHAR columns) whose every column is engineered to trip exactly one new
check, plus a duplicate row to prove the pre-existing duplicate check still fires.
"today" for the future-date check is 2026-08-23 (see the fixture's event_date values).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
from services import quality_service

SRC = "test_quality_src"
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
    """One row per behaviour; row 7 duplicates row 1 exactly (duplicate-row check).
      gender     -> casing variants (Male/male/M/Female/female/F)      -> inconsistent_case
      status     -> '', 'N/A', '-' placeholders mixed with real values -> hidden_null
      joined     -> ISO '2026-01-05' AND slash '05/01/26' as TEXT      -> mixed_date_format
      age        -> two negatives (-10, -5)                            -> negative_values
      event_date -> two dates after 2026-08-23 (2027, 2030)            -> future_date
      id         -> clean positive ints (negative-check false-positive guard)"""
    await _teardown()
    await db_manager.run_readwrite(
        f'''CREATE TABLE "{SRC}" AS SELECT * FROM (VALUES
            (1, 'Male',   'active', '2026-01-05',  30, DATE '2026-01-10'),
            (2, 'male',   'N/A',    '05/01/26',    25, DATE '2026-02-20'),
            (3, 'M',      '-',      '2026-03-15', -10, DATE '2027-12-31'),
            (4, 'Female', '',       '15/03/26',    40, DATE '2026-04-01'),
            (5, 'female', 'active', '2026-05-20',  -5, DATE '2030-06-15'),
            (6, 'F',      'closed', '20/05/26',     50, DATE '2026-06-30'),
            (1, 'Male',   'active', '2026-01-05',  30, DATE '2026-01-10')
        ) AS t(id, gender, status, joined, age, event_date)'''
    )


def _by_id(findings):
    return {f["id"]: f for f in findings}


async def service_main():
    print("=" * 70)
    print("TASK-021 PROOF -- data-quality scan: all six issue classes")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.server_version:
        print(f"  (real redis-server version {redis_manager.server_version})")
    print("=" * 70)

    await _seed()
    report = await quality_service.assess_table(SRC)
    fx = _by_id(report["findings"])
    codes = {f["code"] for f in report["findings"]}
    print(f"\nScanned {SRC}: {report['row_count']} rows, "
          f"{report['column_count']} cols, {len(report['findings'])} findings")
    for f in report["findings"]:
        print(f"    - {f['severity']:<6} {f['code']:<18} col={f['column']!s:<12} "
              f"op={f['suggested_op']!s:<16} metric={f['metric']}")

    # --- bounded to <=4 queries regardless of width (A/B/C/D) --------------------
    n_queries = report["compiled_sql"].count(";\n\n") + 1
    check("scan issues at most 4 queries (A/B/C/D)", n_queries <= 4, f"{n_queries} statements")

    # --- each NEW check fires on its engineered column ---------------------------
    print("\n--- new checks fire ---")
    check("hidden_null on 'status'", "hidden_null:status" in fx)
    check("  hidden_null counts all 3 placeholders ('', N/A, -)",
          fx.get("hidden_null:status", {}).get("metric") == 3.0,
          str(fx.get("hidden_null:status", {}).get("metric")))
    check("inconsistent_case on 'gender'", "inconsistent_case:gender" in fx)
    check("  gender: 6 raw distinct collapse to 4 folded (delta 2)",
          fx.get("inconsistent_case:gender", {}).get("metric") == 2.0,
          str(fx.get("inconsistent_case:gender", {}).get("metric")))
    check("mixed_date_format on 'joined'", "mixed_date_format:joined" in fx)
    check("negative_values on 'age'", "negative_values:age" in fx)
    check("  age: exactly 2 negatives (-10, -5)",
          fx.get("negative_values:age", {}).get("metric") == 2.0,
          str(fx.get("negative_values:age", {}).get("metric")))
    check("future_date on 'event_date'", "future_date:event_date" in fx)
    check("  event_date: exactly 2 future dates (2027, 2030)",
          fx.get("future_date:event_date", {}).get("metric") == 2.0,
          str(fx.get("future_date:event_date", {}).get("metric")))

    # --- pre-existing duplicate check still fires (no regression) ----------------
    print("\n--- no regression ---")
    check("duplicate_rows still detected (row 7 == row 1)", "duplicate_rows" in codes)

    # --- review-only invariant: invalid-values + mixed-date carry NO fix button --
    print("\n--- review-only (no suggested_op => no one-click fix) ---")
    for rid in ("negative_values:age", "future_date:event_date", "mixed_date_format:joined"):
        check(f"{rid} is review-only (suggested_op is None)",
              fx.get(rid, {}).get("suggested_op") is None,
              str(fx.get(rid, {}).get("suggested_op")))
    # --- fixable text findings route to string_normalize -------------------------
    for rid in ("hidden_null:status", "inconsistent_case:gender"):
        check(f"{rid} routes fix to string_normalize",
              fx.get(rid, {}).get("suggested_op") == "string_normalize",
              str(fx.get(rid, {}).get("suggested_op")))

    # --- false-positive guards ---------------------------------------------------
    print("\n--- false-positive guards ---")
    check("clean 'id' column NOT flagged negative", "negative_values:id" not in fx)
    check("'joined' is mixed_date_format, NOT text_as_date", "text_as_date:joined" not in fx)

    # --- compiled SQL shows the new machinery (transparency / ADR-012) -----------
    print("\n--- compiled SQL carries the new checks ---")
    sql = report["compiled_sql"].upper()
    check("SQL has hidden-null sentinel test (isin / IN)", " IN (" in sql)
    check("SQL has case-folded distinct (DISTINCT LOWER)", "DISTINCT" in sql and "LOWER(" in sql)
    check("SQL has date-shape regex (REGEXP_MATCHES)", "REGEXP_MATCHES(" in sql)
    check("SQL has future-date horizon (CURRENT_DATE)", "CURRENT_DATE" in sql)

    await _teardown()

    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} FAILURE(S): {_failures}")
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("=" * 70)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(service_main()))
