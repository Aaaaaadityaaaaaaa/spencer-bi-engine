# TASK-001-FIX-01

## Objective
Obtain and verify proof that the dual-connection design in `duckdb_manager.py` (ADR-003) actually works as intended: the read-only connection genuinely blocks writes, and opening two simultaneous connections to the same DuckDB file does not cause a lock conflict.

## Review Reference
No formal review file exists yet for this — this task closes an item that was flagged during ad-hoc review before the `.ai/` structure was established (see DECISIONS.md ADR-003, CURRENT_STATE.md "Currently Blocked").

## Problems
1. The read-only connection fix was implemented (`self._readonly_conn = duckdb.connect(db_path, read_only=True)`) but never proven with actual test output.
2. Only a DDL write (`CREATE TABLE`) was covered by the originally-requested test; DML writes (`INSERT`/`DELETE`) against an existing table were never tested.
3. Whether two simultaneous connections to the same file (one rw, one ro) works without a lock conflict in this DuckDB version has never been confirmed.

## Required Fixes
1. Run a test that attempts both DDL and DML writes through `get_readonly_connection()` / `run_readonly()` against a table that already has rows, and confirms each is blocked with a real error.
2. Report the exact error type/message DuckDB raises for each blocked attempt.
3. Confirm no lock conflict occurred when both connections were opened simultaneously at startup. If a conflict did occur, report the exact error — do not silently work around it by reverting to a shared connection (this would reintroduce AP-1 in CODING_STANDARDS.md).

## Constraints
Do not change unrelated functionality. Do not introduce architectural changes. If a workaround is needed for a lock conflict, propose it as an `ARCHITECTURAL_CHANGE_REQUEST` rather than implementing it silently.

## Acceptance Criteria
- Actual console output showing all of: `CREATE TABLE` blocked, `INSERT` blocked, `DELETE` blocked, each with the real exception type and message
- Confirmation (via the same run) that connection setup itself succeeded without a lock error
- No test result is accepted as a description — only real, pasted output

## Required Tests
```python
import asyncio
from services.duckdb_manager import db_manager

async def test_readonly_full():
    rw = db_manager.get_readwrite_connection()
    rw.execute("CREATE TABLE probe_table (id INTEGER)")
    rw.execute("INSERT INTO probe_table VALUES (1)")
    rw.close()

    for stmt in [
        "CREATE TABLE test_block (id INTEGER)",
        "DELETE FROM probe_table",
        "INSERT INTO probe_table VALUES (2)",
    ]:
        try:
            await db_manager.run_readonly(stmt)
            print(f"FAIL: '{stmt}' succeeded on read-only connection")
        except Exception as e:
            print(f"PASS: '{stmt}' blocked — {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_readonly_full())
```

## Edge Cases
- What happens if the read-only connection is opened before the read-write connection has created the file? (Should not occur given current `__init__` order, but confirm.)

## Security Considerations
This task exists entirely because of a security property (ADR-003) — treat it accordingly. Do not mark this APPROVED on partial evidence.

## Performance Considerations
None specific to this task.

## Definition Of Done
All three PASS lines are present in real output, with no lock conflict on startup, or an `ARCHITECTURAL_CHANGE_REQUEST` is filed if one occurred.

## Status
READY_FOR_IMPLEMENTATION
