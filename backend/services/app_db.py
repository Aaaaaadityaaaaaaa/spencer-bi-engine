"""Identity + ownership store (TASK-027).

A small SQLAlchemy 2.x layer, deliberately separate from the analytical DuckDB
(rebuildable working data) and Redis (liveness / caches). It holds the two
durable facts multi-tenancy needs: *who* a user is (``users``) and *which*
``session_uuid`` belongs to whom (``datasets``).

One engine, chosen by ``config.APP_DB_URL``: SQLite by default (zero-infra dev,
and what the test-suite runs against) or Postgres in production
(``postgresql+psycopg://...``). Models are kept dialect-neutral -- portable
column types only, no SQLite- or PG-specific features -- so the identical code
runs on both. ``init_db()`` (create_all) is called once at app startup.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import config


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# SQLite needs check_same_thread=False because FastAPI serves from a threadpool
# and a Session may be touched on a different thread than it was created on;
# Postgres ignores it. pool_pre_ping keeps prod connections healthy across idle
# gaps without any tuning knob this wave doesn't need.
_is_sqlite = config.APP_DB_URL.startswith("sqlite")
_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(config.APP_DB_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stored normalized (lower-cased + stripped, see auth_service.normalize_email)
    # so uniqueness is case-insensitive. 320 = max RFC-ish email length.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Dataset(Base):
    """Ownership map: one row per uploaded session (``session_uuid`` -> user). The
    analytical data itself lives in DuckDB (``t_{uuid}_*``) + Redis; this row is
    only the durable 'who owns this uuid' fact the ownership check reads."""

    __tablename__ = "datasets"

    session_uuid: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    primary_table: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


def init_db() -> None:
    """Create tables if absent. Idempotent; called at app startup (main.py) and
    by the test harness. No migration framework this wave -- create_all only,
    which is enough for additive schema on a fresh deploy."""
    Base.metadata.create_all(engine)
