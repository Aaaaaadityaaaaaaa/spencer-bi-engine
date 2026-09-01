import sys
import re

with open('backend/routers/ai.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add WebSocket and query_worker imports
if "from fastapi import APIRouter" in content:
    content = content.replace("from fastapi import APIRouter, Depends, HTTPException", "from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect")

if "from services.query_worker import query_worker" not in content:
    content = content.replace("from services.duckdb_manager import db_manager", "from services.duckdb_manager import db_manager\nfrom services.query_worker import query_worker")

# Update execute_query
old_execute = """async def execute_query(session_uuid: str, payload: ExecuteRequest):
    \"\"\"Run a user-reviewed SELECT and return rows as JSON (synchronous).

    Defense: validate first (fail-closed -- this catches SQL the user edited by
    hand, not just AI output), then execute ONLY inside run_sandboxed (rolled back,
    so even a validator bypass could not mutate data). Column names are recovered
    with a read-only DESCRIBE (run_sandboxed has none), and rows are capped at
    MAX_ROWS with a `truncated` flag. The documented async query_id/poll/MessagePack
    path (/queries/{id} below) stays deferred.\"\"\"
    sql = (payload.sql or "").strip()
    # B (user choice): let the user write the ORIGINAL table name instead of the long
    # t_<uuid>_ physical name. Rewritten AST-level to the physical name before validation,
    # so the tenant-isolation gate still runs on real physical names. AI-generated SQL (which
    # already uses physical names) is unaffected.
    sql = await resolve_aliases(sql, session_uuid)
    if not sql_validator.validate(sql):
        raise HTTPException(
            status_code=400,
            detail="This query was rejected: only a single read-only SELECT is allowed.",
        )

    # S-1 (TASK-029): read-only is necessary but NOT sufficient on the shared
    # single-file DuckDB -- a bare SELECT can still read another tenant's table
    # or a file (read_csv_auto/read_text). Enforce that this query touches ONLY
    # this session's own tables and calls no filesystem/external function.
    scope_reason = sql_validator.scope_violation(sql, session_uuid)
    if scope_reason:
        raise HTTPException(
            status_code=400,
            detail=f"This query was rejected: it {scope_reason}.",
        )

    # Strip a trailing ';' so the statement can be wrapped as a subquery. (Stacked
    # statements were already rejected by the validator; this only tidies a lone
    # trailing terminator so `SELECT ...;` still runs.)
    inner = sql.rstrip(";").rstrip()

    try:
        # Column names/types: DESCRIBE is read-only and also sandboxed (rolled back).
        desc = await db_manager.run_sandboxed(f"DESCRIBE SELECT * FROM ({inner}) _q")
        # Rows, capped: fetch one extra to detect truncation.
        rows_raw = await db_manager.run_sandboxed(f"SELECT * FROM ({inner}) _q LIMIT {MAX_ROWS + 1}")
    except Exception as exc:
        # A validated SELECT can still fail at run time (unknown column, type
        # mismatch). Surface it as a 400 for the editor to display.
        logger.info("execute: query failed at run time: %s", exc)
        raise HTTPException(status_code=400, detail=f"Query failed: {exc}")

    rows = [dict(zip(names, r)) for r in rows_raw]

    return ExecuteResultResponse(
        columns=[PreviewColumn(name=n, type=t) for n, t in zip(names, types)],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )"""

new_execute = """async def execute_query(session_uuid: str, payload: ExecuteRequest):
    \"\"\"Run a user-reviewed SELECT and return a query_id for WebSocket streaming.

    Defense: validate first (fail-closed -- this catches SQL the user edited by
    hand, not just AI output), then submit to query_worker.
    \"\"\"
    sql = (payload.sql or "").strip()
    sql = await resolve_aliases(sql, session_uuid)
    
    if not sql_validator.validate(sql):
        raise HTTPException(
            status_code=400,
            detail="This query was rejected: only a single read-only SELECT is allowed.",
        )

    scope_reason = sql_validator.scope_violation(sql, session_uuid)
    if scope_reason:
        raise HTTPException(
            status_code=400,
            detail=f"This query was rejected: it {scope_reason}.",
        )

    inner = sql.rstrip(";").rstrip()
    
    query_id = query_worker.start_query(session_uuid, inner)
    
    # Return 202 Accepted style payload
    return {"query_id": query_id, "status": "running"}"""

# Replace execute_query logic
content = re.sub(r'async def execute_query.*?return ExecuteResultResponse.*?truncated=truncated,\n    \)', new_execute, content, flags=re.DOTALL)

# Change response_model for execute_query
content = content.replace("@router.post(\"/{session_uuid}/execute\", response_model=ExecuteResultResponse)", "@router.post(\"/{session_uuid}/execute\")")

# Add websocket and cancel endpoints
ws_endpoints = """
@router.websocket("/{session_uuid}/queries/{query_id}/ws")
async def query_websocket(websocket: WebSocket, session_uuid: str, query_id: str):
    await websocket.accept()
    
    job = query_worker.get_status(query_id)
    if not job or job["session_uuid"] != session_uuid:
        await websocket.send_json({"status": "error", "message": "Query not found or unauthorized"})
        await websocket.close()
        return

    if job["status"] in ("completed", "error"):
        if job["status"] == "completed":
            await websocket.send_json({"status": "completed", "result": job["result"]})
        else:
            await websocket.send_json({"status": "error", "message": job["error"]})
        await websocket.close()
        return

    q = await query_worker.subscribe(query_id)
    try:
        while True:
            # Send ping
            await websocket.send_json({"status": "running", "elapsed_ms": int((time.time() - job["start_time"]) * 1000)})
            
            try:
                # Wait for update or timeout to ping again
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_json(msg)
                if msg["status"] in ("completed", "error"):
                    break
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        query_worker.unsubscribe(query_id, q)
        try:
            await websocket.close()
        except Exception:
            pass

@router.post("/{session_uuid}/queries/{query_id}/cancel")
async def cancel_query(session_uuid: str, query_id: str):
    job = query_worker.get_status(query_id)
    if not job or job["session_uuid"] != session_uuid:
        raise HTTPException(status_code=404, detail="Query not found")
    
    query_worker.cancel_query(query_id)
    return {"status": "cancelled"}
"""

content = content + "\n" + ws_endpoints

# Fix time import
if "import time" not in content:
    content = "import time\nimport asyncio\n" + content

with open('backend/routers/ai.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated ai.py for async query worker")
