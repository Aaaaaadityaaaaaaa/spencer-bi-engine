import asyncio
from services.duckdb_manager import db_manager
import sys

async def test_readonly():
    # Attempting to write using the read-only wrapper
    query = "CREATE TABLE test_table (id INTEGER)"
    try:
        await db_manager.run_readonly(query)
        print("FAIL: The statement executed successfully! The connection is not read-only.")
        sys.exit(1)
    except Exception as e:
        print(f"SUCCESS: Read-only protection worked. Error raised:\n{e}")

if __name__ == "__main__":
    asyncio.run(test_readonly())
