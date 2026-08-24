"""FastAPI dependency seam for auth + multi-tenancy (TASK-027).

This is the codebase's first use of FastAPI ``Depends()``. Three gates:
  - ``get_current_user``      -> **401** if the bearer token is missing/invalid/expired
  - ``require_session_owner`` -> **404** if the caller doesn't own the path's
                                 ``session_uuid`` (404 not 403: never reveal that a
                                 uuid exists to a non-owner)
  - ``require_admin``         -> **403** unless the user is a platform admin

``get_db`` yields one short-lived app_db ``Session`` per request and always closes
it. Because FastAPI caches a dependency's result within a request, the single
``get_db`` is shared by ``get_current_user`` and ``require_session_owner`` in the
same request (one Session, not two).
"""
import logging
from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

import config
from services import auth_service, ownership_service
from services.app_db import Dataset, SessionLocal, User
from services.redis_manager import redis_manager

logger = logging.getLogger("spencer.deps")

_UNAUTH = {"WWW-Authenticate": "Bearer"}


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to a User or raise 401. Accepts
    ``Authorization: Bearer <token>`` (scheme match is case-insensitive)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated", headers=_UNAUTH)
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="Invalid authorization header", headers=_UNAUTH)
    try:
        payload = auth_service.decode_token(parts[1].strip())
        user_id = int(payload["sub"])
    except (auth_service.AuthError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers=_UNAUTH)
    user = auth_service.get_user_by_id(db, user_id)
    if user is None:
        # Token is well-formed but the user is gone (deleted) -> treat as unauthenticated.
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers=_UNAUTH)
    return user


def require_session_owner(
    session_uuid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dataset:
    """Gate every ``/sessions/{session_uuid}/...`` route: the caller must own the
    session. Returns **404** (never 403) when the row is absent or owned by someone
    else, so an attacker can't distinguish 'not yours' from 'doesn't exist'. On
    success, slides the Redis liveness marker to the longer owned-session TTL and
    stamps last_active_at (runs after the deploy_guards middleware, so it wins)."""
    ds = ownership_service.get_dataset(db, session_uuid)
    if ds is None or ds.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    redis_manager.touch_session(session_uuid, config.OWNED_SESSION_TTL_SECONDS)
    ownership_service.touch_dataset(db, session_uuid)
    return ds


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
