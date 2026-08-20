from fastapi import APIRouter
from typing import Any

router = APIRouter()

@router.get("/{session_uuid}/data")
async def get_data(session_uuid: str, offset: int = 0, limit: int = 500):
    # Windowed fetch for TanStack Table
    return []

@router.post("/{session_uuid}/chart")
async def build_chart(session_uuid: str, payload: Any):
    # Build + execute GROUP BY from axis bucket config
    # Response is MessagePack encoded rows
    return b""
