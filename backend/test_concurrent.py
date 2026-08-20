import asyncio
from services.duckdb_manager import db_manager

async def test_concurrent_sandboxed_and_readwrite():
    rw = db_manager.get_readwrite_connection()
    # Idempotent: spencer.db is persistent, so without this the test can only
    # ever pass once and later runs die on CatalogException (looks like a
    # security regression when it is only leftover state).
    rw.execute("DROP TABLE IF EXISTS probe_table")
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
