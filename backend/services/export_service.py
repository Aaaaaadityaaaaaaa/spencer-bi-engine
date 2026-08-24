"""Encode a session table (persisted) or in-hand query rows to a downloadable
byte blob. Foundation 4 (Wave 2 / TASK-020): the single writer behind two export
features -- #10 (export the cleaned Table) and #24 (export query results).

Two entry points:
    encode_table(table, fmt)        -> bytes   # #10: a full persisted table
    encode_rows(columns, rows, fmt) -> bytes   # #24: query results already in hand

Native formats (csv/tsv/json/parquet) go through DuckDB ``COPY ... TO`` into a
server-generated temp file (never a client-supplied path), which is read back and
deleted. xlsx has no native DuckDB writer, so it is built with openpyxl -- the same
pure-Python dep the ingestion bridge uses (no runtime network / platform lock-in).

Security: the SELECT source is a ``_quote_ident``-quoted table name the ROUTER has
already resolved against the session's known tables (``_resolve_table`` -> 404); the
COPY target is a server-generated path (tempfile + uuid, single-quote-escaped), so
no user input is interpolated into the COPY statement. Fails closed -> ExportError
-> the router maps it to HTTP 400, never a 500.
"""
import os
import tempfile
import uuid as _uuid
from io import BytesIO
from typing import Any, Dict, List

from services.duckdb_manager import db_manager


class ExportError(Exception):
    """A caller/user-input problem (unsupported format, unreadable table). The
    router maps this to HTTP 400 -- never a 500."""


# Every format encode_table can produce. encode_rows (query results) only needs
# xlsx server-side -- csv/json/clipboard are built client-side from rows in hand.
TABLE_FORMATS = ("csv", "tsv", "json", "parquet", "xlsx")
ROW_FORMATS = ("xlsx",)

_MEDIA = {
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "parquet": "application/octet-stream",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# DuckDB COPY option strings. tsv reuses the csv writer with a real tab delimiter:
# the '\t' below is a literal tab at runtime (mirrors read_csv_auto's delim on the
# ingestion side), so DuckDB writes true tab-separated values.
_COPY_OPTS = {
    "csv": "FORMAT csv, HEADER",
    "tsv": "FORMAT csv, HEADER, DELIMITER '\t'",
    "json": "FORMAT json, ARRAY true",
    "parquet": "FORMAT parquet",
}


def media_type(fmt: str) -> str:
    """Content-Type for a download response; octet-stream for anything unknown."""
    return _MEDIA.get(fmt, "application/octet-stream")


def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier, escaping embedded quotes. Local copy -- a
    service must not import a router; mirrors routers.session._quote_ident."""
    return '"' + name.replace('"', '""') + '"'


def _tmp_path(fmt: str) -> str:
    """A server-generated temp path for COPY TO. Forward slashes so DuckDB reads it
    on Windows too; the name is tempdir + a random uuid, so nothing user-supplied
    reaches the COPY string."""
    p = os.path.join(tempfile.gettempdir(), f"spencer_export_{_uuid.uuid4().hex}.{fmt}")
    return p.replace("\\", "/")


async def encode_table(table: str, fmt: str) -> bytes:
    """Encode a whole persisted session table to `fmt`. `table` is the real table
    name the router already resolved (safe to quote + interpolate)."""
    if fmt not in TABLE_FORMATS:
        raise ExportError(f"Unsupported export format: {fmt}")
    qtable = _quote_ident(table)

    if fmt == "xlsx":
        desc = await db_manager.run_readwrite(f"DESCRIBE {qtable}")
        names = [r[0] for r in (desc or [])]
        rows = await db_manager.run_readwrite(f"SELECT * FROM {qtable} ORDER BY rowid")
        return _rows_to_xlsx(names, rows or [])

    # Native DuckDB writer via COPY TO a server-generated temp file. rowid ordering
    # matches what the grid shows (a hidden pseudocolumn, so it is not in SELECT *).
    tmp = _tmp_path(fmt)
    safe_tmp = tmp.replace("'", "''")  # defense in depth; a uuid path has no quotes
    try:
        await db_manager.run_readwrite(
            f"COPY (SELECT * FROM {qtable} ORDER BY rowid) TO '{safe_tmp}' ({_COPY_OPTS[fmt]})"
        )
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


async def encode_rows(columns: List[str], rows: List[Dict[str, Any]], fmt: str) -> bytes:
    """Encode query-result rows the client already holds. Server-side is xlsx only
    (csv/json/clipboard are built client-side from these same rows). `rows` are dicts
    keyed by column name, as returned by /execute; `columns` fixes the output order."""
    if fmt not in ROW_FORMATS:
        raise ExportError(
            f"Server-side row export supports only {', '.join(ROW_FORMATS)}; got {fmt}"
        )
    matrix = [[row.get(c) for c in columns] for row in rows]
    return _rows_to_xlsx(columns, matrix)


def _rows_to_xlsx(names: List[Any], rows: List) -> bytes:
    """Write a header + rows to an in-memory .xlsx via openpyxl (write-only, for
    bounded memory). String cells are forced to text type so a leading '='/'+'/'-'/'@'
    is stored literally -- this preserves fidelity AND cannot be read as a formula by
    a spreadsheet app. Blocking/CPU work, but bounded by the row caps upstream."""
    import datetime
    from decimal import Decimal
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()

    # bool is a subclass of int, so it passes through as a native boolean cell.
    _passthrough = (int, float, bool, datetime.datetime, datetime.date, datetime.time)

    def cell(value):
        if value is None or isinstance(value, _passthrough):
            return value
        if isinstance(value, Decimal):
            return float(value)
        # A str (or anything else, stringified) becomes an explicit text cell so a
        # leading '=' is never interpreted as a formula.
        s = value if isinstance(value, str) else str(value)
        c = WriteOnlyCell(ws, value=s)
        c.data_type = "s"
        return c

    ws.append([str(n) for n in names])
    for r in rows:
        ws.append([cell(v) for v in r])

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
