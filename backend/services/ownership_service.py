"""Dataset ownership map (TASK-027): thin helpers over the ``datasets`` table that
record which user owns a ``session_uuid`` and answer the ownership question the
``require_session_owner`` dependency asks on every ``/sessions/{uuid}`` request.

Kept separate from auth_service (identity) so the guard's data access is obvious
and independently testable. Every function takes an explicit ``Session`` opened
by the caller / dependency (``deps.get_db``)."""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.app_db import Dataset

logger = logging.getLogger("spencer.ownership")


def record_dataset(
    db: Session,
    session_uuid: str,
    user_id: int,
    primary_table: str,
    file_name: Optional[str],
) -> Dataset:
    """Persist ownership of a freshly created session. Defensive upsert: if a row
    for this uuid somehow already exists, leave the owner intact (uuids are
    server-minted and unique, so a collision here would be a bug, not a rebind)."""
    existing = db.get(Dataset, session_uuid)
    if existing is not None:
        return existing
    ds = Dataset(
        session_uuid=session_uuid,
        user_id=user_id,
        primary_table=primary_table,
        file_name=file_name,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def get_dataset(db: Session, session_uuid: str) -> Optional[Dataset]:
    return db.get(Dataset, session_uuid)


def user_owns(db: Session, session_uuid: str, user_id: int) -> bool:
    ds = db.get(Dataset, session_uuid)
    return ds is not None and ds.user_id == user_id


def list_user_datasets(db: Session, user_id: int) -> List[Dataset]:
    return list(
        db.scalars(
            select(Dataset)
            .where(Dataset.user_id == user_id)
            .order_by(Dataset.last_active_at.desc())
        )
    )


def touch_dataset(db: Session, session_uuid: str) -> None:
    """Stamp last_active_at = now so an actively-used owned session isn't judged
    idle. Paired with the Redis TTL slide in require_session_owner."""
    ds = db.get(Dataset, session_uuid)
    if ds is not None:
        ds.last_active_at = datetime.now(timezone.utc)
        db.commit()


def delete_dataset(db: Session, session_uuid: str) -> bool:
    ds = db.get(Dataset, session_uuid)
    if ds is None:
        return False
    db.delete(ds)
    db.commit()
    return True
