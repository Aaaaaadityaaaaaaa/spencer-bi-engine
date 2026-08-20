from fastapi import APIRouter

router = APIRouter()

@router.post("/kill-query/{query_id}")
async def kill_query(query_id: str):
    # Interrupt a running query
    return {"status": "killed"}
