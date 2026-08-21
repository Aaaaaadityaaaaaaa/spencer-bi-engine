from fastapi import APIRouter
from typing import Any, Optional

from models.schemas import DataResponse, PreviewColumn
from services.duckdb_manager import db_manager
from routers.session import _resolve_table, _quote_ident

router = APIRouter()

# Grid reads are windowed; cap a single window so one request can't pull an
# unbounded result set into memory (the frontend pages via offset/limit).
MAX_LIMIT = 1000


@router.get("/{session_uuid}/data", response_model=DataResponse)
async def get_data(
    session_uuid: str,
    offset: int = 0,
    limit: int = 500,
    table_name: Optional[str] = None,
):
    """Windowed fetch for the virtualized TanStack grid.

    Read-write (non-AI) path: no sqlglot validator (there is no user SQL here).
    Safety comes from resolving the table against the session's known tables
    (_resolve_table -> 404 if unknown), quoting the identifier, and
    coercing+clamping offset/limit to ints. ORDER BY rowid keeps successive
    windows stable (no overlap/skip) for infinite scroll -- rowid is a hidden
    pseudocolumn, so it does not appear in SELECT *.
    """
    table = _resolve_table(session_uuid, table_name)
    qtable = _quote_ident(table)

    off = max(0, int(offset))
    lim = max(1, min(int(limit), MAX_LIMIT))

    total = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {qtable}"))[0][0]

    desc = await db_manager.run_readwrite(f"DESCRIBE {qtable}")
    names = [r[0] for r in (desc or [])]
    types = [r[1] for r in (desc or [])]

    raw = await db_manager.run_readwrite(
        f"SELECT * FROM {qtable} ORDER BY rowid LIMIT {lim} OFFSET {off}"
    )
    rows = [dict(zip(names, r)) for r in (raw or [])]

    return DataResponse(
        columns=[PreviewColumn(name=n, type=t) for n, t in zip(names, types)],
        rows=rows,
        total=total,
        offset=off,
        limit=lim,
    )


@router.post("/{session_uuid}/chart")
async def build_chart(session_uuid: str, payload: Any):
    # Build + execute GROUP BY from axis bucket config
    # Response is MessagePack encoded rows
    return b""
