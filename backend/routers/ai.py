from fastapi import APIRouter
from typing import List
from models.schemas import (
    AskRequest, AskResponse,
    ExecuteRequest, ExecuteResponse,
    QueryPollResponse,
    CustomInstruction
)

router = APIRouter()

@router.post("/{session_uuid}/ask", response_model=AskResponse)
async def ask_question(session_uuid: str, payload: AskRequest):
    # NL question -> generated SQL
    return AskResponse(sql="SELECT ...", cache_hit=False, retries_used=0)

@router.post("/{session_uuid}/execute", response_model=ExecuteResponse)
async def execute_query(session_uuid: str, payload: ExecuteRequest):
    # Execute SQL async, return query_id
    return ExecuteResponse(query_id="query_uuid_stub", status="running")

@router.get("/{session_uuid}/queries/{query_id}", response_model=QueryPollResponse)
async def poll_query(session_uuid: str, query_id: str):
    # Poll execution status/result
    return QueryPollResponse(status="completed", result=b"")

@router.get("/{session_uuid}/instructions", response_model=List[CustomInstruction])
async def get_instructions(session_uuid: str):
    # List Custom Instructions
    return []

@router.post("/{session_uuid}/instructions")
async def add_instruction(session_uuid: str, payload: CustomInstruction):
    # Add/update one term
    return {"status": "added"}

@router.delete("/{session_uuid}/instructions/{term}")
async def delete_instruction(session_uuid: str, term: str):
    # Remove a term
    return {"status": "deleted"}
