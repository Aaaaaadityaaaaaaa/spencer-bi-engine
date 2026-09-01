"""Authentication service (TASK-027): password hashing, JWT issue/verify, and the
user CRUD the ``/auth`` router needs. Pure functions over an app_db ``Session``
(opened by the caller / dependency); the router owns HTTP shaping + status codes.

Password hashing uses the ``bcrypt`` library **directly** rather than passlib:
bcrypt is already a dependency, and passlib's bcrypt backend probes a
``__about__.__version__`` attribute that bcrypt >= 4.1 removed, so passlib would
add only a fragile shim (and a spurious warning). bcrypt considers at most the
first 72 bytes of a password and *raises* past that (bcrypt >= 4.1), so we encode
and slice to 72 bytes before hashing/verifying -- identical to bcrypt's own
historical truncation, with no ValueError.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from services.app_db import User

logger = logging.getLogger("spencer.auth")

# bcrypt only considers the first 72 bytes and raises past that (bcrypt >= 4.1).
_BCRYPT_MAX_BYTES = 72


class AuthError(Exception):
    """Bad credentials, or a missing/invalid/expired token. Router maps to 401."""


class DuplicateUserError(Exception):
    """Email already registered. Router maps to 400."""


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _pw_bytes(password: str) -> bytes:
    return (password or "").encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), (password_hash or "").encode("utf-8"))
    except (ValueError, TypeError):
        # A malformed stored hash must read as a non-match, never a 500.
        return False


# --- JWT --------------------------------------------------------------------

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(hours=config.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid or expired token: {exc}") from exc


# --- User CRUD --------------------------------------------------------------

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def create_user(db: Session, email: str, password: str, is_admin: bool = False) -> User:
    norm = normalize_email(email)
    if get_user_by_email(db, norm) is not None:
        raise DuplicateUserError("That email is already registered")
    user = User(email=norm, password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Lost a concurrent unique race -> deterministic 400, not a 500.
        db.rollback()
        raise DuplicateUserError("That email is already registered") from exc
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        # One message for both cases so we never reveal whether an email exists.
        raise AuthError("Incorrect email or password")
    return user

def update_password(db: Session, user: User, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters")
    user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(user)
