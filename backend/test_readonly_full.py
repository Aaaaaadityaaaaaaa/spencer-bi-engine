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
