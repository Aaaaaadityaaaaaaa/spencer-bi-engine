# TASK-001-FIX-02

## Objective
Implement the transaction-rollback design from ADR-010 (replacing the disproven dual-connection design from ADR-003), and prove with real test output that it actually blocks both DDL and DML from persisting.

## Review Reference
Review of TASK-001-FIX-01's `ARCHITECTURAL_CHANGE_REQUEST` — accepted with modification. See DECISIONS.md ADR-010.

## Problems
1. ADR-003's dual-connection design crashes DuckDB on startup (`ConnectionException`) — confirmed, not in question.
2. The implementer's proposed fallback (single connection + rely solely on `sqlglot` + human review) drops defense-in-depth entirely rather than replacing it.

## Required Fixes
1. Remove `self._readonly_conn` and the second `duckdb.connect(..., read_only=True)` call entirely.
2. Rename `get_readonly_connection()` / `run_readonly()` to something accurate (e.g. `run_sandboxed()`) — do not keep a name implying connection-level read-only enforcement that no longer exists.
3. Implement the new method so that, for any SQL passed to it:
   - `BEGIN TRANSACTION`
   - execute the SQL
   - fetch results (if any)
   - **unconditionally `ROLLBACK`** — regardless of statement type, success, or failure. Never `COMMIT` on this path.
4. `sqlglot` validation (dialect `duckdb`) still runs first, before this method is called at all — this is unchanged, still the first layer.

## Constraints
Do not touch the existing read-write path (`get_readwrite_connection()`/`run_readwrite()`) beyond removing the now-dead second-connection code. Do not change the API contract — this is purely internal to `duckdb_manager.py`.

## Acceptance Criteria
- Real, pasted output proving:
  1. `CREATE TABLE` executed via the new method, then a subsequent query confirms the table does **not** exist afterward
  2. `INSERT` into an existing table via the new method, then a subsequent query confirms the row does **not** exist afterward
  3. `DELETE` of an existing row via the new method, then a subsequent query confirms the row **still exists** afterward
  4. A plain `SELECT` via the new method still returns correct results (the rollback must not break normal read behavior)
- No lock/connection errors on startup (expected, since only one connection now exists — confirm anyway)

## Required Tests
```python
import asyncio
from services.duckdb_manager import db_manager

async def test_transaction_rollback_full():
    rw = db_manager.get_readwrite_connection()
    rw.execute("CREATE TABLE probe_table (id INTEGER)")
    rw.execute("INSERT INTO probe_table VALUES (1)")
    rw.close()

    # DDL: create a table via sandboxed execution, then confirm it doesn't exist
    await db_manager.run_sandboxed("CREATE TABLE test_ddl_block (id INTEGER)")
    check = db_manager.get_readwrite_connection()
    result = check.execute("SELECT table_name FROM duckdb_tables() WHERE table_name = 'test_ddl_block'").fetchall()
    print(f"{'PASS' if not result else 'FAIL'}: DDL rollback — table exists after rollback: {bool(result)}")
    check.close()

    # DML insert: attempt insert via sandboxed execution, confirm row count unchanged
    await db_manager.run_sandboxed("INSERT INTO probe_table VALUES (2)")
    check = db_manager.get_readwrite_connection()
    count = check.execute("SELECT COUNT(*) FROM probe_table").fetchone()[0]
    print(f"{'PASS' if count == 1 else 'FAIL'}: DML insert rollback — row count is {count}, expected 1")
    check.close()

    # DML delete: attempt delete via sandboxed execution, confirm row still exists
    await db_manager.run_sandboxed("DELETE FROM probe_table WHERE id = 1")
    check = db_manager.get_readwrite_connection()
    count = check.execute("SELECT COUNT(*) FROM probe_table").fetchone()[0]
    print(f"{'PASS' if count == 1 else 'FAIL'}: DML delete rollback — row count is {count}, expected 1")
    check.close()

    # Plain SELECT still works normally
    result = await db_manager.run_sandboxed("SELECT * FROM probe_table")
    print(f"{'PASS' if result else 'FAIL'}: normal SELECT via sandboxed path returned: {result}")

if __name__ == "__main__":
    asyncio.run(test_transaction_rollback_full())
```

## Edge Cases
- What happens if the sandboxed SQL itself errors mid-transaction (e.g., malformed query that passed `sqlglot` but fails at execution)? Confirm the transaction still rolls back cleanly and doesn't leave a hanging transaction/lock.

## Security Considerations
This is the sole remaining engine-level defense layer besides `sqlglot` and human review. Do not mark this APPROVED without all four PASS results in real output.

## Performance Considerations
Transaction overhead per AI query is expected to be negligible — not a concern for this task, but worth a one-line note in the implementation report if it's noticeably otherwise.

## Definition Of Done
All four PASS lines present in real output, no startup errors, and the "malformed SQL mid-transaction" edge case confirmed handled without a hanging lock.

## Status
READY_FOR_IMPLEMENTATION