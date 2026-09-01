"""Auth routes (TASK-027): register, login, me. Mounted at ``/auth`` with **no**
session guard -- these mint / read identity rather than touching a dataset.
``register`` honors ``config.ALLOW_REGISTRATION`` read live (so a deployment can
lock down self-serve signup, and tests can monkeypatch it)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import config
from deps import get_current_user, get_db
from models.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from services import auth_service
from services.app_db import User

router = APIRouter()
logger = logging.getLogger("spencer.auth.router")


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if not config.ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="Registration is disabled on this deployment")
    try:
        user = auth_service.create_user(db, payload.email, payload.password)
    except auth_service.DuplicateUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = auth_service.create_access_token(user)
    logger.info("registered user id=%s", user.id)
    return TokenResponse(access_token=token, user=_user_response(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    token = auth_service.create_access_token(user)
    return TokenResponse(access_token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)

from models.schemas import ForgotPasswordRequest, ResetPasswordRequest
from services.redis_manager import RedisManager
redis_manager = RedisManager()
import uuid

@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = auth_service.get_user_by_email(db, payload.email)
    if user:
        reset_token = str(uuid.uuid4())
        # Store in Redis with 15 minute expiration
        redis_manager.set_json(f"reset:{reset_token}", {"user_id": str(user.id)}, ttl=900)
        
        # Mock Emailer: print to server console for local dev
        logger.info(f"==== PASSWORD RESET MOCK EMAIL ====")
        logger.info(f"To reset your password, visit:")
        logger.info(f"http://localhost:5173/login?reset_token={reset_token}")
        logger.info(f"===================================")
        
    return {"status": "ok", "message": "If that email is registered, a reset link was sent."}

@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    
    reset_data = redis_manager.get_json(f"reset:{payload.token}")
    user_id_str = reset_data["user_id"] if reset_data else None

    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        
    user = auth_service.get_user_by_id(db, int(user_id_str))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    try:
        auth_service.update_password(db, user, payload.new_password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    # Invalidate token
    redis_manager.set_json(f"reset:{payload.token}", {}, ttl=1)
    return {"status": "ok", "message": "Password updated successfully"}
