from fastapi import APIRouter
from typing import List, Any
from models.schemas import ScheduleRequest, ScheduleResponse

router = APIRouter()

@router.post("/{session_uuid}/schedules", response_model=ScheduleResponse)
async def create_schedule(session_uuid: str, payload: ScheduleRequest):
    # Create a recurring query job
    return ScheduleResponse(schedule_id="sched_uuid_stub", next_run="2026-08-18T00:00:00Z")

@router.get("/{session_uuid}/schedules", response_model=List[Any])
async def list_schedules(session_uuid: str):
    # List active schedules
    return []

@router.delete("/{session_uuid}/schedules/{schedule_id}")
async def delete_schedule(session_uuid: str, schedule_id: str):
    # Cancel + purge pinned data
    return {"status": "deleted"}

@router.get("/{session_uuid}/schedules/{schedule_id}/runs", response_model=List[Any])
async def list_schedule_runs(session_uuid: str, schedule_id: str):
    # Run history for a schedule
    return []
