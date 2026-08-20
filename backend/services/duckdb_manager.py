import duckdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any

class DuckDBManager:
    def __init__(self, db_path: str = "spencer.db", max_workers: int = 10):
        self.db_path = db_path
        self._conn = duckdb.connect(db_path)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def get_readwrite_connection(self):
        """Returns a cursor for read/write operations."""
        return self._conn.cursor()

    async def execute_async(self, func: Callable, *args, **kwargs) -> Any:
        """Core wrapper routing DuckDB calls through the ThreadPoolExecutor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))

    async def run_readwrite(self, query: str, parameters: tuple = ()) -> Any:
        def _exec():
            cursor = self.get_readwrite_connection()
            try:
                cursor.execute(query, parameters)
                if cursor.description:
                    return cursor.fetchall()
                return None
            finally:
                cursor.close()
        return await self.execute_async(_exec)

    async def run_sandboxed(self, query: str, parameters: tuple = ()) -> Any:
        """Executes AI-generated SQL inside an unconditional rollback transaction for safety."""
        def _exec():
            cursor = self.get_readwrite_connection()
            cursor.execute("BEGIN TRANSACTION")
            try:
                cursor.execute(query, parameters)
                if cursor.description:
                    return cursor.fetchall()
                return None
            finally:
                # Unconditionally rollback regardless of success or exception
                cursor.execute("ROLLBACK")
                cursor.close()
        return await self.execute_async(_exec)

# Global singleton
db_manager = DuckDBManager()
