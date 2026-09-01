from fastapi import APIRouter
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager

router = APIRouter()

@router.get("/health")
def health_check():
    db_status = "connected" if db_manager else "disconnected"
    try:
        redis_status = "connected" if redis_manager._redis else "disconnected"
    except:
        redis_status = "error"
        
    return {
        "status": "ok",
        "db": db_status,
        "redis": redis_status
    }

@router.get("/metrics")
def get_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
