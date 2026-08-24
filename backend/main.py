# Load backend/.env before anything reads the environment, so a locally-placed API
# key (e.g. GEMINI_API_KEY) is honored by the plain `uvicorn main:app` launch with no
# --env-file. Pinned to this file's directory so it works from any cwd; override=False
# keeps a real deployment's env vars authoritative over the file.
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from routers import session, ai, query, schedule, admin
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager
from services import cleanup_service
import config
import asyncio
import logging
import os
import re
import time

logger = logging.getLogger("spencer.main")

app = FastAPI(title="Project Spencer API", version="1.2.0")


# --- Deployability guard middleware (TASK-013) ---------------------------
# Registered BEFORE CORS on purpose: Starlette makes the most-recently-added
# middleware outermost, so adding CORS *after* this guard keeps CORS outermost.
# That matters because this guard can early-return a 413 before the route runs;
# CORS must wrap it so the browser still receives Access-Control-Allow-Origin on
# that error response (else the frontend sees an opaque network failure).
def _is_upload_endpoint(method: str, path: str) -> bool:
    if method != "POST":
        return False
    p = path.rstrip("/")
    if p == "/sessions":
        return True
    return p.startswith("/sessions/") and p.endswith("/tables")


@app.middleware("http")
async def deploy_guards(request: Request, call_next):
    path = request.url.path

    # 1. Early upload-size reject on an honest Content-Length -- catches the
    #    common browser case before the body is spooled. Chunked / absent /
    #    lying Content-Length is caught later by the streaming backstop in
    #    _persist_upload.
    if _is_upload_endpoint(request.method, path):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > config.MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Upload exceeds the {config.MAX_UPLOAD_MB} MB limit"},
                    )
            except ValueError:
                pass

    # 2. Slide the liveness TTL on any /sessions/{uuid}/... activity (including
    #    read-only queries). refresh_session is a no-op if the marker is gone,
    #    so a request to a bogus/reaped uuid does NOT resurrect a session.
    segments = path.strip("/").split("/")
    if len(segments) >= 2 and segments[0] == "sessions":
        redis_manager.refresh_session(segments[1], config.SESSION_TTL_SECONDS)

    return await call_next(request)


# Explicit origin allowlist. `allow_origins=["*"]` together with
# `allow_credentials=True` is invalid per the CORS spec -- browsers reject the
# wildcard on credentialed requests, so the previous config would have failed
# the moment the frontend sent cookies. Override via SPENCER_CORS_ORIGINS.
# Added AFTER deploy_guards so CORS is the outermost layer (see note above).
_origins = os.getenv(
    "SPENCER_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
allowed_origins = [o.strip() for o in _origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router, prefix="/sessions", tags=["Session & Ingestion"])
app.include_router(query.router, prefix="/sessions", tags=["Data Grid & Charting"])
app.include_router(ai.router, prefix="/sessions", tags=["AI Layer"])
app.include_router(schedule.router, prefix="/sessions", tags=["Automation"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])

@app.get("/health", tags=["Admin"])
def health_check():
    return {"status": "ok"}

@app.get("/test-duckdb", tags=["Admin"])
async def test_duckdb():
    # A dummy call that simulates a long-running DB query without blocking the event loop
    def _slow_query():
        cursor = db_manager.get_readwrite_connection()
        try:
            # We use time.sleep to simulate a 2-second DuckDB query block
            time.sleep(2)
            cursor.execute("SELECT 42 AS val")
            return cursor.fetchall()
        finally:
            cursor.close()

    start = time.time()
    res = await db_manager.execute_async(_slow_query)
    duration = time.time() - start
    return {"result": res, "duration": duration}


# DuckDB memory_limit accepts "4GB", "512MiB", "80%", etc. Validate the operator
# knob so a malformed value can never break out of the PRAGMA string literal.
_MEM_LIMIT_RE = re.compile(r"^\s*\d+(\.\d+)?\s*(%|[KMGT]?i?B)?\s*$", re.IGNORECASE)


@app.on_event("startup")
async def startup_event():
    # Runtime hardening (TASK-013 D): apply DuckDB PRAGMAs via the existing
    # run_readwrite -- the frozen duckdb_manager is untouched. Closes the
    # documented-but-unimplemented memory_limit claim and enables bounded RAM /
    # disk spill under concurrent ingest.
    try:
        mem = config.DUCKDB_MEMORY_LIMIT
        if _MEM_LIMIT_RE.match(mem):
            await db_manager.run_readwrite(f"PRAGMA memory_limit='{mem}'")
            applied = await db_manager.run_readwrite("SELECT current_setting('memory_limit')")
            logger.info("DuckDB memory_limit set to %s", applied[0][0] if applied else "?")
        else:
            logger.warning("ignoring malformed SPENCER_DUCKDB_MEMORY_LIMIT=%r", mem)
        if config.DUCKDB_TEMP_DIR:
            safe_tmp = config.DUCKDB_TEMP_DIR.replace("'", "''")
            await db_manager.run_readwrite(f"PRAGMA temp_directory='{safe_tmp}'")
    except Exception:
        logger.exception("startup DuckDB PRAGMA hardening failed")

    # Launch the periodic cleanup sweeper (bare asyncio -- independent of the
    # unbuilt Phase-7 job store). Handle stored on app.state for shutdown cancel.
    app.state.sweeper_task = asyncio.create_task(cleanup_service.sweep_loop())


@app.on_event("shutdown")
async def shutdown_event():
    task = getattr(app.state, "sweeper_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
