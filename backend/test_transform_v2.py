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
    # TASK-018 Wave 1 derive ops
    TransformSplitColumn,
    TransformDateExtract,
    TransformBinColumn,
    # TASK-019 Wave 1b ordered-window ops
    TransformFillDown,
    TransformFlagOutliers,
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

# TASK-018 Wave 1 fixture. Columns chosen so each new op has a clean assertion:
#  - path  : delimited text; "single" has no delimiter -> index 1 => NULL (out-of-range)
#  - code  : letters+digits; regex ([0-9]+) group 1 extracts the number
#  - d     : ISO dates  -> read_csv_auto infers DATE      (2024-01-15 is a Monday)
#  - ts    : ISO stamps -> read_csv_auto infers TIMESTAMP (hour of row 1 = 13)
#  - msg   : messy text (punctuation, vowels, spaces) for regex-replace/strip/pad
#  - amt   : evenly spaced numerics [10..60] for equal-width + quantile binning
CSV_W1 = (
    "path,code,d,ts,msg,amt\n"
    "a-b-c,AB12,2024-01-15,2024-01-15 13:45:30,Hello!!,10\n"
    "x-y-z,CD345,2024-02-20,2024-02-20 08:05:00,WORLD@#,20\n"
    "single,E6,2024-03-10,2024-03-10 23:59:59,foo bar,30\n"
    "p-q-r,GH7,2024-06-30,2024-06-30 00:00:01,BAZ,40\n"
    "m-n,IJ89,2024-09-05,2024-09-05 12:30:00,qux!,50\n"
    "one-two,KL0,2024-12-25,2024-12-25 06:15:45,end,60\n"
)

# TASK-019 Wave 1b fixture (12 rows). Built so both ordered-window ops assert cleanly:
#  - id : 1..12, unique non-null row key (used to address rows in assertions)
#  - g  : text with nulls at ids 1,3,5,12 -> fill-down/up fill the interior nulls
#         and LEAVE a leading null (id1, down) / trailing null (id12, up) in place
#  - v  : eleven 100s + one 200 (id12). n=12 makes the single outlier's z-score
#         (11/sqrt(12) = 3.175) exceed threshold 3.0 -> exactly one row flagged.
CSV_W19 = (
    "id,g,v\n"
    "1,,100\n"
    "2,a,100\n"
    "3,,100\n"
    "4,b,100\n"
    "5,,100\n"
    "6,c,100\n"
    "7,c,100\n"
    "8,c,100\n"
    "9,c,100\n"
    "10,c,100\n"
    "11,c,100\n"
    "12,,200\n"
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


async def _cols_types(tbl):
    """{column_name: duckdb_type} for the live table (TASK-019: assert flag col type)."""
    info = await db_manager.run_readwrite(f'PRAGMA table_info("{tbl}")')
    return {row[1]: row[2] for row in info}


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


async def _expect_reject(session, tbl, param):
    """Apply an op that MUST fail closed. Returns (rejected?, reason). Because
    _apply resets to pristine first and a guard raises before any materialize,
    the table is left untouched at pristine either way."""
    try:
        await _apply(session, tbl, param)
        return (False, "ACCEPTED (!)")
    except transform_service.TransformError as e:
        return (True, str(e))


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


async def task018_main():
    """TASK-018 Wave 1 proof: the four derive ops (split/extract, date parts,
    text toolkit, binning) on a real DuckDB table, with compiled-SQL assertions
    (the verified DuckDB functions), real-effect assertions on a known fixture,
    fail-closed guard branches, and undo restoring the prior schema."""
    print("\n" + "=" * 70)
    print("TASK-018 PROOF -- Wave 1 derive ops "
          "(split/extract, date parts, text toolkit, binning)")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    print("=" * 70)

    await _teardown()

    path = _write_csv("w1.csv", CSV_W1)
    tname, _ = _table_name_for(S_A, "w1.csv")
    await analyze_and_register_table(S_A, tname, path, is_primary=True)
    base_rows = await _rowcount(tname)
    cols = await transform_service._columns_of(tname)
    coltypes = {c: d for c, d in cols}
    print(f"\nRegistered {tname} with {base_rows} rows. Inferred types: {coltypes}")
    check("w1 fixture registered with 6 rows", base_rows == 6, f"rows={base_rows}")

    # AC-3 basis: the date / timestamp / numeric columns must be inferred with the
    # right family, else the date_extract / bin_column TYPE guards would (rightly)
    # reject them and the real-effect assertions below would be meaningless.
    d_t = coltypes.get("d", "").upper()
    ts_t = coltypes.get("ts", "").upper()
    amt_t = coltypes.get("amt", "").upper()
    check("column 'd' inferred as DATE (not TIMESTAMP)",
          "DATE" in d_t and "TIMESTAMP" not in d_t, f"d={d_t}")
    check("column 'ts' inferred as TIMESTAMP", "TIMESTAMP" in ts_t, f"ts={ts_t}")
    check("column 'amt' inferred numeric",
          any(m in amt_t for m in ("INT", "DECIMAL", "DOUBLE", "FLOAT")), f"amt={amt_t}")

    # ------------------------------------------------------------------ #
    print("\n--- #3 split_column (delimiter + regex) ---")
    # delimiter mode: 2nd field (index=1, 0-based) of `path` split on '-'.
    p = TransformSplitColumn(op="split_column", column="path", new_column_name="path_part",
                             mode="delimiter", delimiter="-", index=1)
    sql = _compiled(tname, cols, p)
    print("[split delimiter] " + " ".join(sql.split()))
    check("split delimiter compiles to LIST_EXTRACT/STR_SPLIT",
          "LIST_EXTRACT" in sql and "STR_SPLIT" in sql)
    await _apply(S_A, tname, p)
    check("split_column adds 'path_part'", "path_part" in await _cols(tname))
    check("split delim idx1: 'a-b-c' -> 'b'", await _cell(tname, "path_part", "path", "a-b-c") == "b")
    check("split delim idx1: 'single' (no delim) -> NULL (out of range)",
          await _cell(tname, "path_part", "path", "single") is None)
    check("split delim: exactly 1 NULL (only 'single')",
          await _count_where(tname, "path_part IS NULL") == 1)
    await transform_service.undo(S_A, tname)
    check("undo split_column removes 'path_part'", "path_part" not in await _cols(tname))

    # regex mode: capture group 1 of ([0-9]+) from `code`.
    p = TransformSplitColumn(op="split_column", column="code", new_column_name="code_num",
                             mode="regex", pattern="([0-9]+)", group=1)
    sql = _compiled(tname, cols, p)
    print("[split regex] " + " ".join(sql.split()))
    check("split regex compiles to REGEXP_EXTRACT", "REGEXP_EXTRACT" in sql)
    await _apply(S_A, tname, p)
    check("split regex: 'AB12' -> '12'", await _cell(tname, "code_num", "code", "AB12") == "12")
    check("split regex: 'CD345' -> '345'", await _cell(tname, "code_num", "code", "CD345") == "345")

    # guards
    rej, reason = await _expect_reject(S_A, tname, TransformSplitColumn(
        op="split_column", column="amt", new_column_name="x", mode="delimiter", delimiter="-"))
    check("split_column on a numeric column rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformSplitColumn(
        op="split_column", column="path", new_column_name="path", mode="delimiter", delimiter="-"))
    check("split_column name collision ('path') rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformSplitColumn(
        op="split_column", column="path", new_column_name="x", mode="delimiter", delimiter=""))
    check("split_column empty delimiter rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- #4 date_extract (parts + strftime; hour-on-DATE gated) ---")
    # a-b-c = 2024-01-15 (a MONDAY); one-two = 2024-12-25.
    p = TransformDateExtract(op="date_extract", column="d", new_column_name="yr", mode="part", part="year")
    sql = _compiled(tname, cols, p)
    check("date year compiles to EXTRACT(year FROM ...)", "EXTRACT(year FROM" in sql)
    await _apply(S_A, tname, p)
    check("year of 2024-01-15 == 2024", await _cell(tname, "yr", "path", "a-b-c") == 2024)

    await _apply(S_A, tname, TransformDateExtract(
        op="date_extract", column="d", new_column_name="mo", mode="part", part="month"))
    check("month of a-b-c (Jan) == 1", await _cell(tname, "mo", "path", "a-b-c") == 1)
    check("month of one-two (Dec) == 12", await _cell(tname, "mo", "path", "one-two") == 12)

    await _apply(S_A, tname, TransformDateExtract(
        op="date_extract", column="d", new_column_name="qtr", mode="part", part="quarter"))
    check("quarter of Jan == 1", await _cell(tname, "qtr", "path", "a-b-c") == 1)
    check("quarter of Dec == 4", await _cell(tname, "qtr", "path", "one-two") == 4)

    await _apply(S_A, tname, TransformDateExtract(
        op="date_extract", column="d", new_column_name="doy", mode="part", part="dayofyear"))
    check("dayofyear of 2024-01-15 == 15", await _cell(tname, "doy", "path", "a-b-c") == 15)

    # weekday compiles via DAYOFWEEK arithmetic, NOT EXTRACT (Mon=0 ISO index).
    p = TransformDateExtract(op="date_extract", column="d", new_column_name="wd", mode="part", part="weekday")
    sql = _compiled(tname, cols, p)
    check("weekday compiles to DAYOFWEEK (not EXTRACT)", "DAYOFWEEK" in sql and "EXTRACT" not in sql)
    await _apply(S_A, tname, p)
    check("weekday of 2024-01-15 (Monday) == 0", await _cell(tname, "wd", "path", "a-b-c") == 0)

    p = TransformDateExtract(op="date_extract", column="d", new_column_name="wn", mode="part", part="weekday_name")
    sql = _compiled(tname, cols, p)
    check("weekday_name compiles to a CASE naming 'Monday'", "'Monday'" in sql and "DAYOFWEEK" in sql)
    await _apply(S_A, tname, p)
    check("weekday_name of 2024-01-15 == 'Monday'", await _cell(tname, "wn", "path", "a-b-c") == "Monday")

    # hour requires a TIMESTAMP -> use `ts`.
    p = TransformDateExtract(op="date_extract", column="ts", new_column_name="hr", mode="part", part="hour")
    sql = _compiled(tname, cols, p)
    check("hour compiles to EXTRACT(hour FROM ...)", "EXTRACT(hour FROM" in sql)
    await _apply(S_A, tname, p)
    check("hour of 2024-01-15 13:45:30 == 13", await _cell(tname, "hr", "path", "a-b-c") == 13)

    # strftime reformat.
    p = TransformDateExtract(op="date_extract", column="d", new_column_name="ym", mode="format", date_format="%Y/%m")
    sql = _compiled(tname, cols, p)
    check("format compiles to STRFTIME", "STRFTIME" in sql)
    await _apply(S_A, tname, p)
    check("strftime '%Y/%m' of 2024-01-15 == '2024/01'", await _cell(tname, "ym", "path", "a-b-c") == "2024/01")
    await transform_service.undo(S_A, tname)
    check("undo date_extract removes 'ym'", "ym" not in await _cols(tname))

    # guards
    rej, reason = await _expect_reject(S_A, tname, TransformDateExtract(
        op="date_extract", column="d", new_column_name="x", mode="part", part="hour"))
    check("hour on a DATE column rejected (needs TIMESTAMP)", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformDateExtract(
        op="date_extract", column="msg", new_column_name="x", mode="part", part="year"))
    check("date_extract on a text column rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformDateExtract(
        op="date_extract", column="d", new_column_name="x", mode="format", date_format=""))
    check("date_extract empty format rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- #6 bin_column (equal-width + quantile) ---")
    # amt = [10,20,30,40,50,60]; bins=3.
    p = TransformBinColumn(op="bin_column", column="amt", new_column_name="bin_ew",
                           method="equal_width", bins=3)
    sql = _compiled(tname, cols, p)
    check("equal_width compiles with FLOOR and NO NTILE", "FLOOR" in sql and "NTILE" not in sql)
    await _apply(S_A, tname, p)
    distinct_ew = (await db_manager.run_readwrite(f'SELECT COUNT(DISTINCT bin_ew) FROM "{tname}"'))[0][0]
    check("equal_width bins=3 -> 3 distinct buckets", distinct_ew == 3, f"distinct={distinct_ew}")
    check("equal_width: min(amt=10) in bucket 0", await _cell(tname, "bin_ew", "amt", 10) == 0)
    check("equal_width: max(amt=60) in top bucket 2", await _cell(tname, "bin_ew", "amt", 60) == 2)
    mn, mx = (await db_manager.run_readwrite(f'SELECT MIN(bin_ew), MAX(bin_ew) FROM "{tname}"'))[0]
    check("equal_width buckets within [0, 2]", mn == 0 and mx == 2, f"min/max={mn}/{mx}")

    p = TransformBinColumn(op="bin_column", column="amt", new_column_name="bin_q",
                           method="quantile", bins=3)
    sql = _compiled(tname, cols, p)
    check("quantile compiles to NTILE(3) and NO FLOOR", "NTILE(3)" in sql and "FLOOR" not in sql)
    await _apply(S_A, tname, p)
    distinct_q = (await db_manager.run_readwrite(f'SELECT COUNT(DISTINCT bin_q) FROM "{tname}"'))[0][0]
    check("quantile bins=3 -> 3 distinct buckets", distinct_q == 3, f"distinct={distinct_q}")
    check("quantile: amt=10 in bucket 0", await _cell(tname, "bin_q", "amt", 10) == 0)
    check("quantile: amt=60 in bucket 2", await _cell(tname, "bin_q", "amt", 60) == 2)
    await transform_service.undo(S_A, tname)
    check("undo bin_column removes 'bin_q'", "bin_q" not in await _cols(tname))

    # guards (bins is UNCONSTRAINED in pydantic -> range is a service 400, not a 422)
    rej, reason = await _expect_reject(S_A, tname, TransformBinColumn(
        op="bin_column", column="amt", new_column_name="x", method="equal_width", bins=1))
    check("bins=1 (below 2) rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformBinColumn(
        op="bin_column", column="amt", new_column_name="x", method="equal_width", bins=51))
    check("bins=51 (above 50) rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformBinColumn(
        op="bin_column", column="msg", new_column_name="x", method="equal_width", bins=3))
    check("bin_column on a text column rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- #5 text toolkit (regex-replace / strip-special / pad) ---")
    # A/B on the SAME find string proves the regex flag flips semantics: the
    # literal string '[aeiou]' occurs nowhere, so regex=False is a no-op; regex=True
    # treats it as a character class and replaces the vowels.
    await _apply(S_A, tname, TransformStringNormalize(
        op="string_normalize", column="msg", find="[aeiou]", replace="_", regex=False))
    check("literal find '[aeiou]' matches nothing: 'Hello!!' unchanged",
          await _cell(tname, "msg", "amt", 10) == "Hello!!")

    p = TransformStringNormalize(op="string_normalize", column="msg", find="[aeiou]", replace="_", regex=True)
    sql = _compiled(tname, cols, p)
    check("regex replace compiles to REGEXP_REPLACE(..., 'g')", "REGEXP_REPLACE" in sql and "'g'" in sql)
    await _apply(S_A, tname, p)
    check("regex '[aeiou]' replaces vowels: 'Hello!!' -> 'H_ll_!!'",
          await _cell(tname, "msg", "amt", 10) == "H_ll_!!")
    check("regex leaves UPPERCASE vowels alone: 'WORLD@#' unchanged",
          await _cell(tname, "msg", "amt", 20) == "WORLD@#")

    # literal find/replace path is UNCHANGED from today (byte-identical behavior).
    await _apply(S_A, tname, TransformStringNormalize(
        op="string_normalize", column="msg", find="oo", replace="00", regex=False))
    check("literal replace still substitutes: 'foo bar' -> 'f00 bar'",
          await _cell(tname, "msg", "amt", 30) == "f00 bar")
    check("literal replace leaves non-matches alone: 'Hello!!' unchanged",
          await _cell(tname, "msg", "amt", 10) == "Hello!!")

    p = TransformStringNormalize(op="string_normalize", column="msg", strip_special=True)
    sql = _compiled(tname, cols, p)
    check("strip_special compiles to REGEXP_REPLACE [^A-Za-z0-9 ]",
          "REGEXP_REPLACE" in sql and "[^A-Za-z0-9 ]" in sql)
    await _apply(S_A, tname, p)
    check("strip_special: 'Hello!!' -> 'Hello'", await _cell(tname, "msg", "amt", 10) == "Hello")
    check("strip_special: 'WORLD@#' -> 'WORLD'", await _cell(tname, "msg", "amt", 20) == "WORLD")
    check("strip_special keeps spaces: 'foo bar' -> 'foo bar'",
          await _cell(tname, "msg", "amt", 30) == "foo bar")

    p = TransformStringNormalize(op="string_normalize", column="msg",
                                 pad_side="left", pad_length=8, pad_char="*")
    sql = _compiled(tname, cols, p)
    check("lpad compiles to REPEAT (CASE, no truncation)", "REPEAT" in sql)
    await _apply(S_A, tname, p)
    check("lpad w8 '*': 'BAZ' -> '*****BAZ'", await _cell(tname, "msg", "amt", 40) == "*****BAZ")
    check("lpad w8 '*': 'Hello!!' -> '*Hello!!'", await _cell(tname, "msg", "amt", 10) == "*Hello!!")

    await _apply(S_A, tname, TransformStringNormalize(
        op="string_normalize", column="msg", pad_side="right", pad_length=8, pad_char="*"))
    check("rpad w8 '*': 'BAZ' -> 'BAZ*****'", await _cell(tname, "msg", "amt", 40) == "BAZ*****")

    # guards
    rej, reason = await _expect_reject(S_A, tname, TransformStringNormalize(
        op="string_normalize", column="msg", pad_side="left", pad_length=8, pad_char="ab"))
    check("multi-char pad_char rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformStringNormalize(
        op="string_normalize", column="msg", pad_side="left", pad_length=0, pad_char="*"))
    check("pad_length=0 rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- free plumbing: preview (derived col + 0 delta + compiled SQL), history ---")
    await _reset_to_pristine(S_A, tname)
    prev = await transform_service.preview_transform(S_A, tname, TransformSplitColumn(
        op="split_column", column="path", new_column_name="pp", mode="delimiter", delimiter="-", index=0))
    pv_cols = [c["name"] for c in prev["columns"]]
    print(f"    preview(split) columns: {pv_cols}")
    check("preview(split) shows the derived column 'pp'", "pp" in pv_cols, f"cols={pv_cols}")
    check("preview(split) row-delta is 0 (add-column op)", prev["row_count_delta"] == 0,
          f"delta={prev['row_count_delta']}")
    check("preview(split) exposes compiled SQL (LIST_EXTRACT)", "LIST_EXTRACT" in prev["compiled_sql"])
    check("preview did NOT add 'pp' to the live table", "pp" not in await _cols(tname))

    await _reset_to_pristine(S_A, tname)
    await transform_service.apply_transform(S_A, tname, TransformBinColumn(
        op="bin_column", column="amt", new_column_name="b", method="quantile", bins=4))
    hist = transform_service.get_history(S_A, tname)
    check("history logs the bin_column op",
          any(s["op"] == "bin_column" for s in hist["steps"]),
          f"ops={[s['op'] for s in hist['steps']]}")

    await _teardown()


async def task019_main():
    """TASK-019 Wave 1b proof: the two ordered-window ops (fill_down forward/back,
    flag_outliers z-score) on a real DuckDB table -- compiled-SQL assertions (the
    verified rowid window / STDDEV_SAMP), real-effect assertions on a known fixture
    (interior nulls filled; leading/trailing null preserved; the single outlier
    flagged), fail-closed guards, and undo restoring the prior state."""
    print("\n" + "=" * 70)
    print("TASK-019 PROOF -- Wave 1b ordered-window ops (fill down/up, flag outliers)")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    print("=" * 70)

    await _teardown()

    path = _write_csv("w19.csv", CSV_W19)
    tname, _ = _table_name_for(S_A, "w19.csv")
    await analyze_and_register_table(S_A, tname, path, is_primary=True)
    base_rows = await _rowcount(tname)
    cols = await transform_service._columns_of(tname)
    coltypes = {c: d for c, d in cols}
    print(f"\nRegistered {tname} with {base_rows} rows. Inferred types: {coltypes}")
    check("w19 fixture registered with 12 rows", base_rows == 12, f"rows={base_rows}")
    check("g has 4 nulls at ids 1,3,5,12",
          await _count_where(tname, "g IS NULL") == 4,
          f"nulls={await _count_where(tname, 'g IS NULL')}")

    # ------------------------------------------------------------------ #
    print("\n--- #7a fill_down (direction=down: carry last non-null forward) ---")
    p = TransformFillDown(op="fill_down", column="g", direction="down")
    sql = _compiled(tname, cols, p)
    print("[fill down] " + " ".join(sql.split()))
    check("fill down compiles to LAST_VALUE ... IGNORE NULLS OVER (ORDER BY rowid)",
          "LAST_VALUE" in sql and "IGNORE NULLS" in sql and "rowid" in sql)
    rc = await _apply(S_A, tname, p)
    check("fill_down preserves row count (in-place, 12 rows)", rc == 12, f"rows={rc}")
    check("fill down: id2 null -> 'a' (from id2? no, id1 null) -> carries id2's own 'a'",
          await _cell(tname, "g", "id", 2) == "a")
    check("fill down: id3 null -> 'a' (last non-null before it)",
          await _cell(tname, "g", "id", 3) == "a")
    check("fill down: id5 null -> 'b' (id4)", await _cell(tname, "g", "id", 5) == "b")
    check("fill down: id12 null -> 'c' (last non-null before it)",
          await _cell(tname, "g", "id", 12) == "c")
    check("fill down LEAVES the leading null (id1) as NULL",
          await _cell(tname, "g", "id", 1) is None)
    check("fill down: exactly the 1 leading null remains",
          await _count_where(tname, "g IS NULL") == 1,
          f"nulls={await _count_where(tname, 'g IS NULL')}")
    await transform_service.undo(S_A, tname)
    check("undo fill_down restores all 4 original nulls",
          await _count_where(tname, "g IS NULL") == 4)

    # ------------------------------------------------------------------ #
    print("\n--- #7b fill_down (direction=up: carry next non-null backward) ---")
    p = TransformFillDown(op="fill_down", column="g", direction="up")
    sql = _compiled(tname, cols, p)
    print("[fill up] " + " ".join(sql.split()))
    check("fill up compiles to FIRST_VALUE ... IGNORE NULLS OVER (ORDER BY rowid)",
          "FIRST_VALUE" in sql and "IGNORE NULLS" in sql and "rowid" in sql)
    await _apply(S_A, tname, p)
    check("fill up: id1 null -> 'a' (next non-null, id2)", await _cell(tname, "g", "id", 1) == "a")
    check("fill up: id3 null -> 'b' (next non-null, id4)", await _cell(tname, "g", "id", 3) == "b")
    check("fill up: id5 null -> 'c' (next non-null, id6)", await _cell(tname, "g", "id", 5) == "c")
    check("fill up LEAVES the trailing null (id12) as NULL",
          await _cell(tname, "g", "id", 12) is None)
    check("fill up: exactly the 1 trailing null remains",
          await _count_where(tname, "g IS NULL") == 1)
    await transform_service.undo(S_A, tname)

    # guards
    rej, reason = await _expect_reject(S_A, tname, TransformFillDown(
        op="fill_down", column="nope", direction="down"))
    check("fill_down on an unknown column rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- #7c flag_outliers (z-score) ---")
    p = TransformFlagOutliers(op="flag_outliers", column="v", new_column_name="v_out",
                              method="zscore", threshold=3.0)
    sql = _compiled(tname, cols, p)
    print("[flag_outliers] " + " ".join(sql.split()))
    check("flag_outliers compiles with STDDEV_SAMP + ABS over a full-frame window",
          "STDDEV_SAMP" in sql and "ABS" in sql and "OVER" in sql)
    await _apply(S_A, tname, p)
    check("flag_outliers adds 'v_out'", "v_out" in await _cols(tname))
    check("flag_outliers 'v_out' is BOOLEAN",
          "BOOL" in (await _cols_types(tname)).get("v_out", "").upper(),
          f"type={(await _cols_types(tname)).get('v_out')}")
    check("z-score: the lone 200 (id12) is flagged True", await _cell(tname, "v_out", "id", 12) is True)
    check("z-score: a cluster value (id1, v=100) is NOT flagged", await _cell(tname, "v_out", "id", 1) is False)
    check("z-score threshold 3.0: EXACTLY one row flagged",
          await _count_where(tname, "v_out = TRUE") == 1,
          f"flagged={await _count_where(tname, 'v_out = TRUE')}")
    await transform_service.undo(S_A, tname)
    check("undo flag_outliers removes 'v_out'", "v_out" not in await _cols(tname))

    # a very high threshold flags nothing (proves threshold is honored, not hard-coded)
    await _apply(S_A, tname, TransformFlagOutliers(
        op="flag_outliers", column="v", new_column_name="v_out2", method="zscore", threshold=10.0))
    check("z-score threshold 10.0: nothing flagged",
          await _count_where(tname, "v_out2 = TRUE") == 0,
          f"flagged={await _count_where(tname, 'v_out2 = TRUE')}")

    # guards
    rej, reason = await _expect_reject(S_A, tname, TransformFlagOutliers(
        op="flag_outliers", column="g", new_column_name="x", method="zscore", threshold=3.0))
    check("flag_outliers on a text column rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformFlagOutliers(
        op="flag_outliers", column="v", new_column_name="v", method="zscore", threshold=3.0))
    check("flag_outliers name collision ('v') rejected", rej, reason)
    rej, reason = await _expect_reject(S_A, tname, TransformFlagOutliers(
        op="flag_outliers", column="v", new_column_name="x", method="zscore", threshold=0.0))
    check("flag_outliers threshold=0 rejected", rej, reason)

    # ------------------------------------------------------------------ #
    print("\n--- free plumbing: preview (fill 0-delta + compiled SQL), history ---")
    await _reset_to_pristine(S_A, tname)
    prev = await transform_service.preview_transform(S_A, tname, TransformFillDown(
        op="fill_down", column="g", direction="down"))
    check("preview(fill_down) row-delta is 0 (in-place op)", prev["row_count_delta"] == 0,
          f"delta={prev['row_count_delta']}")
    check("preview(fill_down) exposes compiled SQL (LAST_VALUE)", "LAST_VALUE" in prev["compiled_sql"])
    pv_cols = [c["name"] for c in prev["columns"]]
    check("preview(fill_down) does NOT project rowid", "rowid" not in pv_cols, f"cols={pv_cols}")
    check("preview did NOT change the live table's null count",
          await _count_where(tname, "g IS NULL") == 4)

    await _reset_to_pristine(S_A, tname)
    await transform_service.apply_transform(S_A, tname, TransformFillDown(
        op="fill_down", column="g", direction="down"))
    hist = transform_service.get_history(S_A, tname)
    check("history logs the fill_down op",
          any(s["op"] == "fill_down" for s in hist["steps"]),
          f"ops={[s['op'] for s in hist['steps']]}")

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

    # --- TASK-018 derive ops end-to-end: happy-path 200 + fail-closed 400 ---
    r = client.post("/sessions", files={"file": ("w1.csv", CSV_W1, "text/csv")})
    check("POST /sessions (w1) returns 200", r.status_code == 200, f"status={r.status_code}")
    b2 = r.json()
    sid2 = b2["session_uuid"]
    tname2 = b2["table_name"]
    check("w1 upload has 6 rows", b2["row_count"] == 6, f"row_count={b2['row_count']}")

    # split_column happy path -> 200
    r = client.post(f"/sessions/{sid2}/transform", json={
        "op": "split_column", "column": "path", "new_column_name": "pp",
        "mode": "delimiter", "delimiter": "-", "index": 1})
    check("POST /transform split_column returns 200", r.status_code == 200, f"status={r.status_code}")

    # date_extract hour-on-DATE -> fail-closed 400 (not a 500)
    r = client.post(f"/sessions/{sid2}/transform", json={
        "op": "date_extract", "column": "d", "new_column_name": "x", "mode": "part", "part": "hour"})
    check("date_extract hour-on-DATE -> HTTP 400", r.status_code == 400, f"status={r.status_code}")

    # bin_column bins out of range -> 400 from the SERVICE guard, proving it is not
    # a 422 (bins is unconstrained in the pydantic model on purpose).
    r = client.post(f"/sessions/{sid2}/transform", json={
        "op": "bin_column", "column": "amt", "new_column_name": "x", "method": "equal_width", "bins": 99})
    check("bin_column bins=99 -> HTTP 400 (service guard, not 422)", r.status_code == 400, f"status={r.status_code}")

    # preview of a derive op -> 200 exposing the compiled SQL (NTILE for quantile)
    r = client.post(f"/sessions/{sid2}/transform/preview", json={
        "op": "bin_column", "column": "amt", "new_column_name": "bq", "method": "quantile", "bins": 3})
    check("POST /transform/preview bin_column returns 200", r.status_code == 200, f"status={r.status_code}")
    check("preview bin_column exposes NTILE in compiled SQL", "NTILE" in r.json().get("compiled_sql", ""))

    # --- TASK-019 ordered-window ops end-to-end: happy-path 200 + fail-closed 400 ---
    r = client.post("/sessions", files={"file": ("w19.csv", CSV_W19, "text/csv")})
    check("POST /sessions (w19) returns 200", r.status_code == 200, f"status={r.status_code}")
    b3 = r.json()
    sid3 = b3["session_uuid"]
    tname3 = b3["table_name"]
    check("w19 upload has 12 rows", b3["row_count"] == 12, f"row_count={b3['row_count']}")

    # fill_down happy path -> 200, still 12 rows (in-place)
    r = client.post(f"/sessions/{sid3}/transform", json={
        "op": "fill_down", "column": "g", "direction": "down"})
    check("POST /transform fill_down returns 200 with 12 rows",
          r.status_code == 200 and r.json().get("row_count") == 12, f"body={r.json()}")

    # flag_outliers happy path -> 200
    r = client.post(f"/sessions/{sid3}/transform", json={
        "op": "flag_outliers", "column": "v", "new_column_name": "v_out",
        "method": "zscore", "threshold": 3.0})
    check("POST /transform flag_outliers returns 200", r.status_code == 200, f"status={r.status_code}")

    # flag_outliers threshold=0 -> fail-closed 400 (service guard, not 422)
    r = client.post(f"/sessions/{sid3}/transform", json={
        "op": "flag_outliers", "column": "v", "new_column_name": "x",
        "method": "zscore", "threshold": 0})
    check("flag_outliers threshold=0 -> HTTP 400 (service guard)", r.status_code == 400, f"status={r.status_code}")

    # flag_outliers on a text column -> 400
    r = client.post(f"/sessions/{sid3}/transform", json={
        "op": "flag_outliers", "column": "g", "new_column_name": "x", "method": "zscore", "threshold": 3.0})
    check("flag_outliers on a text column -> HTTP 400", r.status_code == 400, f"status={r.status_code}")

    # preview flag_outliers -> 200 exposing STDDEV_SAMP in compiled SQL
    r = client.post(f"/sessions/{sid3}/transform/preview", json={
        "op": "flag_outliers", "column": "v", "new_column_name": "vp", "method": "zscore", "threshold": 3.0})
    check("POST /transform/preview flag_outliers returns 200", r.status_code == 200, f"status={r.status_code}")
    check("preview flag_outliers exposes STDDEV_SAMP in compiled SQL",
          "STDDEV_SAMP" in r.json().get("compiled_sql", ""))

    async def _cleanup_http():
        await _drop_like(f"%{tname}%")
        await _drop_like(f"%{tname2}%")
        await _drop_like(f"%{tname3}%")
        _redis_cleanup(sid, sid2, sid3)
    asyncio.run(_cleanup_http())


def main():
    asyncio.run(service_main())
    asyncio.run(task018_main())
    asyncio.run(task019_main())
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
