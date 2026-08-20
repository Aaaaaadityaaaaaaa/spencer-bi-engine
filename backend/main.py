from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import session, ai, query, schedule, admin
import os

app = FastAPI(title="Project Spencer API", version="1.2.0")

# Explicit origin allowlist. `allow_origins=["*"]` together with
# `allow_credentials=True` is invalid per the CORS spec -- browsers reject the
# wildcard on credentialed requests, so the previous config would have failed
# the moment the frontend sent cookies. Override via SPENCER_CORS_ORIGINS.
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

from services.duckdb_manager import db_manager
import time

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

@app.on_event("startup")
def startup_event():
    # Initialize APScheduler, Redis pool, DuckDB connections here
    pass

@app.on_event("shutdown")
def shutdown_event():
    # Cleanup resources
    pass
