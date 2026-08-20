"""Adversarial proof for services/sql_validator.py.

The validator replaced a stub that returned True unconditionally, so the point
here is not "does a SELECT pass" -- it is "does anything that writes get through".
Idempotent and side-effect free (pure parsing, no DB access). See AP-7.
"""
from services.sql_validator import sql_validator

MUST_ALLOW = [
    "SELECT * FROM t",
    "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
    "WITH c AS (SELECT 1 AS x) SELECT x FROM c",
    "SELECT * FROM a JOIN b ON a.id = b.id WHERE a.x > 5 ORDER BY a.x LIMIT 10",
    "SELECT * FROM a UNION ALL SELECT * FROM b",
    "SELECT SUM(revenue - cost) AS profit FROM sales",
    "SELECT * FROM t WHERE name = 'Robert; DROP TABLE students'",  # write only inside a string literal
]

MUST_REJECT = [
    # --- statement stacking ---
    "SELECT 1; DROP TABLE t",
    "SELECT 1; DELETE FROM t",
    # --- outright DDL / DML ---
    "DROP TABLE t",
    "DELETE FROM t",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET a = 1",
    "CREATE TABLE x (id INTEGER)",
    "ALTER TABLE t ADD COLUMN c INTEGER",
    "TRUNCATE TABLE t",
    # --- writes smuggled inside CTEs / subqueries ---
    "WITH c AS (DELETE FROM t RETURNING *) SELECT * FROM c",
    "WITH c AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM c",
    "WITH c AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM c",
    # --- DuckDB-specific escape hatches ---
    "ATTACH 'evil.db' AS evil",
    "COPY t TO 'C:/exfil.csv'",
    "SET memory_limit = '99GB'",
    # --- garbage / empty ---
    "",
    "   ",
    "NOT SQL AT ALL !!!",
]


def run():
    failures = []

    for sql in MUST_ALLOW:
        if not sql_validator.validate(sql):
            failures.append(("FALSE REJECT (blocks legit query)", sql))

    for sql in MUST_REJECT:
        if sql_validator.validate(sql):
            failures.append(("FALSE ACCEPT (SECURITY HOLE)", sql))

    total = len(MUST_ALLOW) + len(MUST_REJECT)
    print(f"allow-cases: {len(MUST_ALLOW)}   reject-cases: {len(MUST_REJECT)}   total: {total}")

    if failures:
        for kind, sql in failures:
            print(f"  FAIL [{kind}]: {sql!r}")
        print(f"FAIL: {len(failures)}/{total} cases wrong")
        return False

    print(f"PASS: all {total} cases correct "
          f"({len(MUST_ALLOW)} reads allowed, {len(MUST_REJECT)} writes/garbage rejected)")
    return True


if __name__ == "__main__":
    run()
