"""Adversarial proof for the per-tenant scope gate (S-1, TASK-029).

`sql_validator.validate()` proves a query is a pure read; `scope_violation()`
proves it reads ONLY the caller's own tables and calls no file/external function.
On the shared single-file DuckDB that second gate is what actually stops one
tenant reading another's rows -- or the .env / identity DB. Pure parsing, no DB
access. Mirrors the MUST_ALLOW / MUST_REJECT idiom of test_sql_validator.py.

Run:  python backend/test_execute_scope.py   (exit 0 = all cases correct)
"""
from services.sql_validator import sql_validator

# The authenticated caller owns this session; its tables are t_<uuid>_* .
SELF = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
_self = SELF.replace("-", "_")
_other = OTHER.replace("-", "_")

# Must be ALLOWED: reads confined to the caller's own tables (rich analytical SQL).
MUST_ALLOW = [
    f"SELECT * FROM t_{_self}_data",
    f"SELECT region, COUNT(*) FROM t_{_self}_sales GROUP BY region ORDER BY 2 DESC",
    f"WITH c AS (SELECT * FROM t_{_self}_data) SELECT * FROM c",
    f"SELECT x.id FROM t_{_self}_a x JOIN t_{_self}_b b ON x.id = b.id",
    f"SELECT * FROM backup_{_self}_data",
    f"SELECT SUM(rev) FILTER (WHERE d > DATE '2020-01-01') FROM t_{_self}_s",
    f"SELECT DATE_TRUNC('month', d) m, AVG(v) FROM t_{_self}_t GROUP BY 1",
    f"SELECT * FROM t_{_self}_a WHERE name IN (SELECT name FROM t_{_self}_b)",
]

# Must be REJECTED: any reach outside the caller's own tables.
MUST_REJECT = [
    f"SELECT * FROM t_{_other}_data",                                   # another tenant's table
    f"SELECT * FROM t_{_self}_a JOIN t_{_other}_b USING (id)",          # join to foreign table
    f"SELECT * FROM t_{_self}_a UNION ALL SELECT * FROM t_{_other}_b",  # foreign table via UNION
    f"WITH c AS (SELECT * FROM t_{_other}_x) SELECT * FROM c",          # foreign table hidden in CTE
    f"SELECT * FROM t_{_self}_a WHERE id IN (SELECT id FROM t_{_other}_b)",  # foreign subquery
    "SELECT read_text('/app/.env')",                                    # file read (scalar fn)
    "SELECT * FROM read_csv_auto('/app/uploads/x/f.csv')",              # file read (table fn)
    "SELECT content FROM read_blob('/app/spencer_app.db')",             # identity DB (hashes)
    "SELECT * FROM glob('/etc/*')",                                     # filesystem listing
    "SELECT * FROM information_schema.tables",                          # cross-tenant catalog enum
    "SELECT * FROM duckdb_tables()",                                    # cross-tenant catalog enum
    "SELECT * FROM main.some_other_table",                             # schema-qualified escape
]


def run():
    failures = []

    for sql in MUST_ALLOW:
        reason = sql_validator.scope_violation(sql, SELF)
        if reason is not None:
            failures.append(("FALSE REJECT (blocks own-tenant query)", sql, reason))

    for sql in MUST_REJECT:
        reason = sql_validator.scope_violation(sql, SELF)
        if reason is None:
            failures.append(("FALSE ACCEPT (CROSS-TENANT / FILE READ)", sql, None))

    total = len(MUST_ALLOW) + len(MUST_REJECT)
    print(f"scope_violation: allow={len(MUST_ALLOW)} reject={len(MUST_REJECT)} total={total}")
    if failures:
        for kind, sql, reason in failures:
            print(f"  FAIL [{kind}]: {sql!r}  ->  {reason!r}")
        print(f"FAIL: {len(failures)}/{total} cases wrong")
        return False
    print(f"PASS: all {total} cases correct")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
