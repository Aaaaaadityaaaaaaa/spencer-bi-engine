"""Dashboard persistence router.
Allows saving and loading user dashboards to the server instead of just localStorage.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException

from deps import get_current_user, get_db
from models.schemas import DashboardCreate, DashboardUpdate, DashboardResponse
from services.app_db import User, Dashboard
from sqlalchemy.orm import Session

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])

@router.get("/", response_model=List[DashboardResponse])
def list_dashboards(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    dashboards = db.query(Dashboard).filter(Dashboard.user_id == user.id).all()
    return dashboards

@router.post("/", response_model=DashboardResponse)
def create_dashboard(
    req: DashboardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    dash = Dashboard(
        user_id=user.id,
        session_uuid=req.session_uuid,
        name=req.name,
        pages_json=req.pages_json
    )
    db.add(dash)
    db.commit()
    db.refresh(dash)
    return dash

@router.put("/{dashboard_id}", response_model=DashboardResponse)
def update_dashboard(
    dashboard_id: int,
    req: DashboardUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    dash = db.query(Dashboard).filter(Dashboard.id == dashboard_id, Dashboard.user_id == user.id).first()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    if req.name is not None:
        dash.name = req.name
    if req.pages_json is not None:
        dash.pages_json = req.pages_json
        
    db.commit()
    db.refresh(dash)
    return dash

@router.delete("/{dashboard_id}")
def delete_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    dash = db.query(Dashboard).filter(Dashboard.id == dashboard_id, Dashboard.user_id == user.id).first()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    db.delete(dash)
    db.commit()
    return {"status": "deleted"}
