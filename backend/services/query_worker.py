import asyncio
import uuid
import time
import logging
from typing import Dict, Any

from services.duckdb_manager import db_manager, current_session_id

logger = logging.getLogger("spencer.query_worker")

class QueryWorker:
    def __init__(self):
        # Maps query_id -> dict of state
        self._jobs: Dict[str, Dict[str, Any]] = {}
        # Maps query_id -> list of asyncio.Queue (for websocket subscribers)
        self._subscribers: Dict[str, list[asyncio.Queue]] = {}

    def start_query(self, session_uuid: str, sql: str) -> str:
        query_id = str(uuid.uuid4())
        self._jobs[query_id] = {
            "status": "running",
            "session_uuid": session_uuid,
            "sql": sql,
            "start_time": time.time(),
            "result": None,
            "error": None
        }
        self._subscribers[query_id] = []
        
        # Fire and forget execution
        asyncio.create_task(self._run(query_id, session_uuid, sql))
        return query_id

    async def _run(self, query_id: str, session_uuid: str, sql: str):
        # We must set context var for the worker thread so DuckDB routes correctly!
        current_session_id.set(session_uuid)
        try:
            # First, fetch columns (DESCRIBE is read-only)
            desc = await db_manager.run_sandboxed(f"DESCRIBE SELECT * FROM ({sql}) _q")
            if not desc:
                raise ValueError("Query returned no columns")
            names = [r[0] for r in desc]
            types = [r[1] for r in desc]
            
            # Then execute main query capped at 1000 rows
            limit = 1000
            rows_raw = await db_manager.run_sandboxed(f"SELECT * FROM ({sql}) _q LIMIT {limit + 1}")
            
            rows = []
            if rows_raw:
                truncated = len(rows_raw) > limit
                rows_to_send = rows_raw[:limit]
                rows = [dict(zip(names, r)) for r in rows_to_send]
            else:
                truncated = False
                
            self._jobs[query_id]["status"] = "completed"
            self._jobs[query_id]["result"] = {
                "columns": [{"name": n, "type": t} for n, t in zip(names, types)],
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated
            }
            await self._broadcast(query_id, {"status": "completed", "result": self._jobs[query_id]["result"]})
            
        except Exception as e:
            # If interrupted by user, duckdb throws IOException/RuntimeError
            logger.info(f"Query {query_id} failed or cancelled: {e}")
            self._jobs[query_id]["status"] = "error"
            self._jobs[query_id]["error"] = str(e)
            await self._broadcast(query_id, {"status": "error", "message": str(e)})
            
        finally:
            # Clean up memory after 5 minutes
            asyncio.create_task(self._cleanup_later(query_id))
            
    async def _broadcast(self, query_id: str, message: dict):
        if query_id in self._subscribers:
            for q in self._subscribers[query_id]:
                await q.put(message)

    async def subscribe(self, query_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        if query_id not in self._subscribers:
            self._subscribers[query_id] = []
        self._subscribers[query_id].append(q)
        return q
        
    def unsubscribe(self, query_id: str, q: asyncio.Queue):
        if query_id in self._subscribers and q in self._subscribers[query_id]:
            self._subscribers[query_id].remove(q)
            
    def get_status(self, query_id: str) -> dict:
        return self._jobs.get(query_id)
        
    def cancel_query(self, query_id: str):
        job = self._jobs.get(query_id)
        if job and job["status"] == "running":
            # Interrupt the underlying duckdb connection
            db_manager.interrupt_session(job["session_uuid"])
            # The running query will instantly throw an exception, updating the status to error
            
    async def _cleanup_later(self, query_id: str):
        await asyncio.sleep(300)
        self._jobs.pop(query_id, None)
        self._subscribers.pop(query_id, None)

query_worker = QueryWorker()
