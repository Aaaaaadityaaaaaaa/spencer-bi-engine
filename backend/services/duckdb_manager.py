import duckdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, Dict
import os
import contextvars
import config
import logging

logger = logging.getLogger("spencer.db")

# ContextVar for the current session UUID. Propagated automatically to ThreadPoolExecutor in Python 3.9+
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_session_id", default=None)

class DuckDBManager:
    def __init__(self, global_db_path: str = "spencer.db", max_workers: int = 10):
        self.global_db_path = global_db_path
        # The global connection is used for catalog-level sweeps and global pragmas
        self._global_conn = duckdb.connect(global_db_path)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._conns: Dict[str, duckdb.DuckDBPyConnection] = {}
        
        self.sessions_dir = os.path.join(os.path.dirname(config.UPLOADS_DIR), "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

    def get_readwrite_connection(self):
        """Returns a cursor for read/write operations for the appropriate session."""
        session_id = current_session_id.get()
        
        if not session_id:
            # Fallback to global if no session is in context (e.g., admin sweeps, startup pragmas)
            return self._global_conn.cursor()
            
        if session_id not in self._conns:
            db_path = os.path.join(self.sessions_dir, f"session_{session_id}.db")
            conn = duckdb.connect(db_path)
            
            # Apply memory limit per connection
            mem_limit = os.getenv("SPENCER_DUCKDB_MEMORY_LIMIT", "4GB")
            conn.execute(f"PRAGMA memory_limit='{mem_limit}'")
            
            self._conns[session_id] = conn
            logger.info(f"Opened per-session DuckDB file: {db_path}")
            
        return self._conns[session_id].cursor()

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
        
    def close_and_delete_session(self, session_id: str):
        """Called by cleanup_service to garbage collect the session."""
        if session_id in self._conns:
            self._conns[session_id].close()
            del self._conns[session_id]
        
        db_path = os.path.join(self.sessions_dir, f"session_{session_id}.db")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                if os.path.exists(db_path + ".wal"):
                    os.remove(db_path + ".wal")
            except Exception as e:
                logger.error(f"Failed to delete session DB file {db_path}: {e}")

# Global singleton
db_manager = DuckDBManager()
