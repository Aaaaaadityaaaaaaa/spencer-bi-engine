from fastapi import APIRouter, HTTPException, Response
from typing import Any, Optional

from models.schemas import (
    DataResponse,
    PreviewColumn,
    AggregateRequest,
    AggregateResponse,
    ColumnProfile,
    ColumnValues,
    QualityReport,
    ExportRowsRequest,
)
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager
from services import aggregate_service, profile_service, quality_service, export_service
from routers.session import _resolve_table, _quote_ident

router = APIRouter()

# Grid reads are windowed; cap a single window so one request can't pull an
# unbounded result set into memory (the frontend pages via offset/limit).
MAX_LIMIT = 1000

# Cap a single row-export payload (#24). /execute already trims results at the
# server row cap, so a legitimate export is well under this; the cap just bounds a
# hand-crafted request's memory/CPU (openpyxl builds the whole sheet in memory).
MAX_EXPORT_ROWS = 100_000


# Numeric DuckDB types eligible for the grid's heatmap colour scale. Matched by
# uppercased prefix so parameterized types (DECIMAL(18,3)) and unsigned aliases
# are all covered; BOOLEAN is deliberately excluded (not a continuous scale).
_NUMERIC_PREFIXES = (
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
    "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC",
)


def _is_numeric_type(duckdb_type: str) -> bool:
    t = (duckdb_type or "").upper()
    return any(t.startswith(p) for p in _NUMERIC_PREFIXES)


def _parse_sort(sort: Optional[str], valid_names: list) -> list:
    """Parse a ``"col:dir,col2:dir2"`` sort spec into ``[(col, "ASC"|"DESC"), ...]``.

    Every column MUST be one of ``valid_names`` (the LIVE schema) and every
    direction MUST be asc/desc -- anything else is a client error (400), so no
    unvalidated token is ever interpolated into the ORDER BY. Returns ``[]`` for
    an empty/None spec (the caller then orders by rowid alone, unchanged behaviour).
    """
    if not sort or not sort.strip():
        return []
    valid = set(valid_names)
    out: list = []
    for term in sort.split(","):
        term = term.strip()
        if not term:
            continue
        col, _, direction = term.partition(":")
        col = col.strip()
        direction = (direction.strip() or "asc").lower()
        if col not in valid:
            raise HTTPException(status_code=400, detail=f"unknown sort column: {col!r}")
        if direction not in ("asc", "desc"):
            raise HTTPException(status_code=400, detail=f"invalid sort direction: {direction!r}")
        out.append((col, direction.upper()))
    return out


@router.get("/{session_uuid}/data", response_model=DataResponse)
async def get_data(
    session_uuid: str,
    offset: int = 0,
    limit: int = 500,
    table_name: Optional[str] = None,
    sort: Optional[str] = None,
    q: Optional[str] = None,
):
    """Windowed fetch for the virtualized grid, with optional server-side
    multi-sort and substring search (TASK-022).

    Read-write (non-AI) path: no sqlglot validator (there is no user SQL here).
    Safety comes from: resolving the table against the session's known tables
    (_resolve_table -> 404 if unknown) and quoting the identifier; validating
    every ``sort`` column against the LIVE schema and restricting the direction to
    asc/desc (never interpolated blindly); and passing the ``q`` search term as a
    BOUND PARAMETER to ILIKE (never concatenated), with %/_/\\ escaped so it
    matches a literal substring. coerce+clamp keeps offset/limit in range.

    ORDER BY always ends in ``rowid`` -- a hidden pseudocolumn absent from
    ``SELECT *`` -- so successive windows stay stable (no overlap/skip) for
    infinite scroll even when the user-chosen sort keys tie.
    """
    table = _resolve_table(session_uuid, table_name)
    qtable = _quote_ident(table)

    off = max(0, int(offset))
    lim = max(1, min(int(limit), MAX_LIMIT))

    desc = await db_manager.run_readwrite(f"DESCRIBE {qtable}")
    names = [r[0] for r in (desc or [])]
    types = [r[1] for r in (desc or [])]

    sort_spec = _parse_sort(sort, names)  # validates -> 400 on bad col/direction

    # --- optional search: literal substring ILIKE across every column ---------
    # Cast each column to text so a numeric/date column is searchable too. The
    # term is a single bound parameter reused per column; LIKE metacharacters are
    # escaped so a '%' in the box searches for a literal percent, not a wildcard.
    where_sql = ""
    params: tuple = ()
    term = (q or "").strip()
    if term and names:
        esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{esc}%"
        clauses = " OR ".join(
            f"CAST({_quote_ident(n)} AS VARCHAR) ILIKE ? ESCAPE '\\'" for n in names
        )
        where_sql = f" WHERE ({clauses})"
        params = tuple([pat] * len(names))

    # total reflects the (optional) filter so the grid's "x / y rows" is honest.
    total = (
        await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {qtable}{where_sql}", params)
    )[0][0]

    order_terms = [f"{_quote_ident(c)} {d} NULLS LAST" for c, d in sort_spec]
    order_terms.append("rowid")  # stable tiebreak / pagination anchor
    order_sql = " ORDER BY " + ", ".join(order_terms)

    # SELECT rowid alongside the row so the grid can address an exact cell for
    # in-cell editing (TASK-041 #5). rowid is a base-table pseudocolumn absent from
    # SELECT * / DESCRIBE, so `names` still describes only the real columns; the
    # rowid rides in column 0 and is split back out into a parallel array below.
    raw = await db_manager.run_readwrite(
        f"SELECT rowid, * FROM {qtable}{where_sql}{order_sql} LIMIT {lim} OFFSET {off}", params
    )
    rowids = [int(r[0]) for r in (raw or [])]
    rows = [dict(zip(names, r[1:])) for r in (raw or [])]

    # --- heatmap ranges: whole-table numeric [min, max], first window only ----
    # Computed once per (re)load (offset 0) and cached client-side, and left
    # UNfiltered so the colour scale stays stable while the user searches. One
    # bounded aggregate over the numeric columns; None when there are none.
    ranges: Optional[Dict[str, List[float]]] = None
    if off == 0:
        num_cols = [n for n, t in zip(names, types) if _is_numeric_type(t)]
        if num_cols:
            sel = ", ".join(
                f"MIN({_quote_ident(n)}), MAX({_quote_ident(n)})" for n in num_cols
            )
            agg = await db_manager.run_readwrite(f"SELECT {sel} FROM {qtable}")
            if agg and agg[0]:
                flat = agg[0]
                built: Dict[str, List[float]] = {}
                for idx, n in enumerate(num_cols):
                    lo, hi = flat[2 * idx], flat[2 * idx + 1]
                    if lo is not None and hi is not None:
                        built[n] = [float(lo), float(hi)]
                ranges = built or None

    return DataResponse(
        columns=[PreviewColumn(name=n, type=t) for n, t in zip(names, types)],
        rows=rows,
        total=total,
        offset=off,
        limit=lim,
        ranges=ranges,
        rowids=rowids,
    )


@router.post("/{session_uuid}/aggregate", response_model=AggregateResponse)
async def aggregate_data(
    session_uuid: str,
    payload: AggregateRequest,
    table_name: Optional[str] = None,
):
    """One KPI or chart aggregation for the Canvas dashboard (Phase 5 / TASK-011).

    Same read-write (non-AI) path as get_data: the table is resolved against the
    session's known tables (_resolve_table -> 404 if unknown), so there is no user
    SQL and no sqlglot validator. The actual SELECT is Ibis-compiled from the typed
    payload against the LIVE schema (ADR-012 -- no client-assembled SQL), then run
    through db_manager.run_readwrite. Single-table only (ADR-006); the /chart
    MessagePack stub below is a separate, future large-result path.
    """
    table = _resolve_table(session_uuid, table_name)
    try:
        result = await aggregate_service.aggregate(table, payload)
    except aggregate_service.AggregateError as exc:
        # User-input problem (unknown column, non-numeric measure, bad aggregation).
        raise HTTPException(status_code=400, detail=str(exc))
    return AggregateResponse(**result)


@router.get("/{session_uuid}/profile/column", response_model=ColumnProfile)
async def profile_column(
    session_uuid: str,
    column: str,
    table_name: Optional[str] = None,
):
    """Statistical profile of one column for the Table data-prep panel (TASK-015).

    Read-only inspection, same non-AI path as get_data/aggregate: the table is
    resolved against the session's known tables (_resolve_table -> 404 if unknown),
    the column is validated against the LIVE schema, and every SELECT is Ibis-compiled
    (ADR-012 -- no client-assembled SQL) then run via db_manager.run_readwrite.
    `column` is a required query param. Single-table only (ADR-006).
    """
    table = _resolve_table(session_uuid, table_name)
    try:
        result = await profile_service.profile_column(table, column)
    except profile_service.ProfileError as exc:
        # User-input problem (unknown column). 400, not 500.
        raise HTTPException(status_code=400, detail=str(exc))
    return ColumnProfile(**result)


@router.get("/{session_uuid}/column/values", response_model=ColumnValues)
async def column_values(
    session_uuid: str,
    column: str,
    table_name: Optional[str] = None,
):
    """Distinct values of one column for the cleaning dialog's find/replace dropdown
    (TASK-042). Read-only, same non-AI path as profile_column: the table is resolved
    against the session's known tables (_resolve_table -> 404 if unknown), the column is
    validated against the LIVE schema, and the SELECT is Ibis-compiled (ADR-012 -- no
    client-assembled SQL). Bounded response (`truncated` when the column has more distinct
    values than returned). `column` is a required query param. Single-table only (ADR-006).
    """
    table = _resolve_table(session_uuid, table_name)
    try:
        result = await profile_service.distinct_values(table, column)
    except profile_service.ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ColumnValues(**result)


@router.get("/{session_uuid}/quality", response_model=QualityReport)
async def quality_report(
    session_uuid: str,
    table_name: Optional[str] = None,
):
    """Whole-table data-quality scan for the Table data-prep panel (TASK-016).

    Read-only inspection, same non-AI path as get_data/aggregate/profile: the table
    is resolved against the session's known tables (_resolve_table -> 404 if unknown);
    the service enumerates columns from the LIVE schema itself (no column input from
    the client) and every SELECT is Ibis-compiled (ADR-012 -- no client-assembled SQL)
    then run via db_manager.run_readwrite. Single-table only (ADR-006).
    """
    table = _resolve_table(session_uuid, table_name)
    try:
        result = await quality_service.assess_table(table)
    except quality_service.QualityError as exc:
        # User-input problem (unknown/empty table). 400, not 500.
        raise HTTPException(status_code=400, detail=str(exc))
    return QualityReport(**result)


# --- Export (Round-trip data, Wave 2 / TASK-020) ----------------------------

@router.get("/{session_uuid}/export")
async def export_table(
    session_uuid: str,
    format: str = "csv",
    table_name: Optional[str] = None,
):
    """Download a whole session table (#10). Same non-AI path as get_data: the table
    is resolved against the session's known tables (_resolve_table -> 404), then encoded
    by export_service (DuckDB COPY for csv/tsv/json/parquet; openpyxl for xlsx). Returns
    raw bytes with a download Content-Disposition; the browser client sets the final
    filename. An unsupported `format` fails closed as 400."""
    table = _resolve_table(session_uuid, table_name)
    fmt = (format or "").lower()
    try:
        data = await export_service.encode_table(table, fmt)
    except export_service.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=data,
        media_type=export_service.media_type(fmt),
        headers={"Content-Disposition": f'attachment; filename="spencer-export.{fmt}"'},
    )


@router.post("/{session_uuid}/export/rows")
async def export_rows(session_uuid: str, payload: ExportRowsRequest):
    """Download query-result rows the client already holds (#24) as .xlsx (CSV/JSON/
    clipboard are done client-side). Requires a live session and caps the row count so a
    crafted request can't exhaust memory. Column order follows `payload.columns`."""
    if not redis_manager.session_alive(session_uuid):
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if len(payload.rows) > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"Too many rows to export ({len(payload.rows)} > {MAX_EXPORT_ROWS})",
        )
    try:
        data = await export_service.encode_rows(payload.columns, payload.rows, payload.format)
    except export_service.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=data,
        media_type=export_service.media_type(payload.format),
        headers={"Content-Disposition": f'attachment; filename="query-results.{payload.format}"'},
    )


@router.post("/{session_uuid}/chart")
async def build_chart(session_uuid: str, payload: Any):
    # Build + execute GROUP BY from axis bucket config
    # Response is MessagePack encoded rows
    return b""
