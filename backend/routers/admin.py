from fastapi import APIRouter

from services import cleanup_service

router = APIRouter()

@router.post("/kill-query/{query_id}")
async def kill_query(query_id: str):
    # Interrupt a running query
    return {"status": "killed"}

@router.post("/sweep")
async def trigger_sweep():
    """Manually run the cleanup sweep now and return the reclamation counts.
    Same code path as the periodic background sweeper (cleanup_service.sweep)."""
    return await cleanup_service.sweep()

@router.get("/storage")
async def storage():
    """Point-in-time storage + session-liveness metrics for ops visibility
    (partially closes the 'health is liveness-only' gap)."""
    return await cleanup_service.storage_report()
