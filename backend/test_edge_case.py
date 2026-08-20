import asyncio
from services.duckdb_manager import db_manager

async def test_edge_case():
    try:
        await db_manager.run_sandboxed("SELECT * FROM non_existent_table")
        print("FAIL: Should have raised an exception")
    except Exception as e:
        print("Caught expected exception.")
    
    # Check if the connection is still usable
    result = await db_manager.run_sandboxed("SELECT 42")
    if result:
        print("PASS: Connection is still usable and not locked in a broken transaction.")
    else:
        print("FAIL: Connection might be locked.")

if __name__ == "__main__":
    asyncio.run(test_edge_case())
