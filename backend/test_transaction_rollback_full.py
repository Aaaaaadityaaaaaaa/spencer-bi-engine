import asyncio
from services.duckdb_manager import db_manager

async def test_transaction_rollback_full():
    rw = db_manager.get_readwrite_connection()
    # Idempotent: spencer.db is persistent, so without this the test can only
    # ever pass once and later runs die on CatalogException (looks like a
    # security regression when it is only leftover state).
    rw.execute("DROP TABLE IF EXISTS probe_table")
    rw.execute("DROP TABLE IF EXISTS test_ddl_block")
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
