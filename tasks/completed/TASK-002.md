# TASK-002

## Title
Verify concurrency safety of `run_sandboxed()` under simultaneous DB access

## Objective
Confirm that DuckDB correctly isolates a `run_sandboxed()` transaction (BEGIN/ROLLBACK) from concurrent regular read-write operations, when both occur simultaneously on different threads via the same `ThreadPoolExecutor`-managed connection.

## Context
TASK-001-FIX-02 proved `run_sandboxed()` correct under sequential execution only (see REVIEW.md). This connection is now shared between all regular operations and sandboxed AI execution — a configuration that didn't exist when Phase 1's concurrency wrapper was originally built and verified. This gap must close before the AI layer (Phase 6) goes live under real usage; it does not block Day 4 ingestion, which doesn't call `run_sandboxed()`.

## Requirements
- Fire a `run_sandboxed()` call and a `run_readwrite()` call concurrently (not sequentially) against the same connection, repeated across multiple trials
- Confirm the `run_readwrite()` write persists correctly and is unaffected by the concurrent transaction's rollback
- Confirm the `run_sandboxed()` call still correctly rolls back its own operation
- Confirm no deadlock, hang, or exception occurs from the concurrent access itself

## Existing Components
`backend/services/duckdb_manager.py` — `run_sandboxed()`, `run_readwrite()`, the `ThreadPoolExecutor` wrapper.

## Files Expected To Change
Likely none in `duckdb_manager.py` if it passes as-is — this task is primarily verification. If a real isolation problem is found, that becomes a new `ARCHITECTURAL_CHANGE_REQUEST`, not a silent fix.

## Files That Must NOT Change
Do not modify the transaction logic to "make the test pass" — if a real race condition is found, report it, don't paper over it.

## Technical Constraints
Test must use genuine concurrent execution (e.g., `asyncio.gather()` firing both calls at once), not sequential `await`s — that was the gap in the previous task.

## Dependencies
TASK-001-FIX-02 (completed).

## Implementation Guidance
```python
import asyncio
from services.duckdb_manager import db_manager

async def test_concurrent_sandboxed_and_readwrite():
    rw = db_manager.get_readwrite_connection()
    rw.execute("CREATE TABLE probe_table (id INTEGER)")
    rw.execute("INSERT INTO probe_table VALUES (1)")
    rw.close()

    async def sandboxed_attempt():
        return await db_manager.run_sandboxed("INSERT INTO probe_table VALUES (999)")

    async def real_write():
        return await db_manager.run_readwrite("INSERT INTO probe_table VALUES (2)")

    # Fire both simultaneously, repeated across several trials
    for trial in range(5):
        await asyncio.gather(sandboxed_attempt(), real_write())

    check = db_manager.get_readwrite_connection()
    rows = check.execute("SELECT id FROM probe_table ORDER BY id").fetchall()
    check.close()
    print(f"Final rows: {rows}")
    # Expect: id=1 (original) + one id=2 per trial (5 total) = 6 rows
    # Expect: id=999 (sandboxed) must NEVER appear, in any trial
    ids = [r[0] for r in rows]
    print(f"{'PASS' if 999 not in ids else 'FAIL'}: sandboxed writes never persisted under concurrency")
    print(f"{'PASS' if ids.count(2) == 5 else 'FAIL'}: all 5 concurrent real writes persisted correctly, got {ids.count(2)}")

if __name__ == "__main__":
    asyncio.run(test_concurrent_sandboxed_and_readwrite())
```

## Acceptance Criteria
- Real output showing both PASS conditions above, across at least 5 concurrent trials
- No exception, hang, or deadlock during the test run

## Tests Required
The script above, run as-is, with real pasted output.

## Edge Cases
- What if `asyncio.gather()` schedules both on the exact same thread pool worker simultaneously — does the test still meaningfully exercise concurrent access, or does Python's GIL/executor scheduling reduce this to effectively sequential? If so, note it in the report — this is a real limitation of Python-level concurrency testing worth being honest about, not something to hide.

## Security Considerations
This is the last unverified piece of the AI-query security model (alongside sqlglot validation and human review).

## Performance Considerations
None specific.

## Definition Of Done
Both PASS conditions confirmed in real output across multiple concurrent trials, with the GIL/scheduling caveat honestly addressed in the report either way.

## Status
READY_FOR_IMPLEMENTATION