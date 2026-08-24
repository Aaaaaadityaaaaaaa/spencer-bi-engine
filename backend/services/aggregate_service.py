"""Phase 5 aggregation for the Canvas dashboard (TASK-011).

KPI cards and chart tiles both reduce to one shape: an optional GROUP BY dimension
plus an aggregate over a measure. Exactly like the Phase 3 structured transforms
(ADR-007/014/015), the query is built as an **Ibis expression on an unbound table**
and compiled to DuckDB SQL text -- Ibis is a compiler here, it never opens its own
connection -- and the compiled SELECT is executed through the existing
``db_manager.run_readwrite`` wrapper.

Only typed params travel from the client (dimension / measure / aggregation); the
column names are validated against the LIVE schema (re-fetched per request via the
shared ``_columns_of`` PRAGMA, never cached -- a transform can add/drop/rename a
column) before Ibis builds the expression, so there is no client-assembled SQL on
this path (ADR-012). Single-table only (ADR-006) -- the router resolves the table.

This mirrors ``transform_service`` and deliberately reuses its hard-won helpers
(the DuckDB-type -> Ibis-dtype map with its fallback, the fresh column fetch, and
the unbound-table builder) rather than duplicating them.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

import ibis

from services.duckdb_manager import db_manager
from services.transform_service import _ibis_dtype, _unbound, _columns_of  # noqa: F401 (reused helpers)

logger = logging.getLogger("spencer.aggregate")

# Chart series are meant to be small + readable (top-N categories); clamp the
# client-supplied limit so one request can't group an unbounded key space.
MAX_CATEGORIES = 200
DEFAULT_LIMIT = 50

# A 2-D breakdown (TASK-025) fans the primary series into one sub-series per
# breakdown value. That is a legend, so it must stay small + readable -- cap the
# number of breakdown categories hard (top-M by magnitude), independent of `limit`.
MAX_SERIES = 12

_NUMERIC_AGGS = frozenset({"sum", "avg"})
_ALLOWED_AGGS = frozenset({"sum", "avg", "count", "count_distinct", "min", "max"})


class AggregateError(Exception):
    """User-input problem (unknown column, non-numeric measure, bad aggregation).
    The router maps this to HTTP 400, not 500 -- it is not a server bug."""


def _jsonable(v: Any) -> Any:
    """Coerce a DuckDB scalar to a JSON-friendly value: Decimal -> float,
    date/datetime -> ISO string; None/int/float/str/bool pass through unchanged.
    Keeps the response predictable for the frontend (e.g. MIN over a DATE column
    becomes an ISO string, not a Python date that would serialize inconsistently)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _agg_expr(t, measure: Optional[str], aggregation: str):
    """The named Ibis aggregate expression `value`. Assumes validation already ran."""
    if aggregation == "count":
        # COUNT(*) when no measure; COUNT(<col>) (non-null) when a measure is given.
        return t.count() if measure is None else t[measure].count()
    col = t[measure]  # measure is guaranteed non-None here by _validate
    if aggregation == "count_distinct":
        return col.nunique()
    if aggregation == "sum":
        return col.sum()
    if aggregation == "avg":
        return col.mean()
    if aggregation == "min":
        return col.min()
    if aggregation == "max":
        return col.max()
    # Unreachable: _validate rejects anything outside _ALLOWED_AGGS.
    raise AggregateError(f"unsupported aggregation '{aggregation}'")


def _validate(t, colnames, dimension: Optional[str], series: Optional[str], measure: Optional[str], aggregation: str) -> None:
    """Fail-closed checks; every failure maps to HTTP 400 (never a 500)."""
    if aggregation not in _ALLOWED_AGGS:
        raise AggregateError(f"unsupported aggregation '{aggregation}'")
    if dimension is not None and dimension not in colnames:
        raise AggregateError(f"column '{dimension}' not found")
    if series is not None and series not in colnames:
        raise AggregateError(f"breakdown column '{series}' not found")
    if measure is not None and measure not in colnames:
        raise AggregateError(f"column '{measure}' not found")

    # Only plain `count` may omit a measure (=> COUNT(*)); everything else needs one.
    if measure is None:
        if aggregation != "count":
            raise AggregateError(f"aggregation '{aggregation}' requires a measure column")
        return

    dtype = t[measure].type()
    if aggregation in _NUMERIC_AGGS and not dtype.is_numeric():
        raise AggregateError(f"'{aggregation}' needs a numeric column; '{measure}' is {dtype}")
    if aggregation in ("min", "max") and not (dtype.is_numeric() or dtype.is_temporal()):
        raise AggregateError(f"'{aggregation}' needs a numeric or date/time column; '{measure}' is {dtype}")


def _apply_filters(t, colnames, filters):
    """AND together each equality cross-filter as an Ibis predicate, applied BEFORE
    the aggregation. The column is validated against the live schema; the value rides
    as a typed Ibis literal -- never string-interpolated (ADR-012). ``value=None``
    means IS NULL (the "(null)" bar/slice). Returns the filtered table expression."""
    if not filters:
        return t
    for f in filters:
        if f.column not in colnames:
            raise AggregateError(f"filter column '{f.column}' not found")
        column = t[f.column]
        t = t.filter(column.isnull() if f.value is None else column == f.value)
    return t


def _isin_pred(col, values):
    """Ibis predicate for ``col IN (values)`` that also matches NULL when None is in
    the list. `values` are RAW DuckDB scalars (a date stays a ``date``), so Ibis emits
    correctly-typed literals -- never a DATE-vs-ISO-string mismatch. Returns None only
    when `values` is empty (callers short-circuit before filtering in that case)."""
    non_null = [v for v in values if v is not None]
    pred = col.isin(non_null) if non_null else None
    if any(v is None for v in values):
        null_pred = col.isnull()
        pred = null_pred if pred is None else (pred | null_pred)
    return pred


async def aggregate(table_name: str, req) -> Dict[str, Any]:
    """Run one KPI (dimension=None) or grouped series (dimension set) aggregation.

    Returns a plain dict matching AggregateResponse. Raises AggregateError (->400)
    for any bad column / type / aggregation combination.
    """
    columns = await _columns_of(table_name)  # fresh schema, never cached
    if not columns:
        raise AggregateError(f"table '{table_name}' has no columns or does not exist")
    colnames = {name for name, _ in columns}

    dimension: Optional[str] = req.dimension
    series_dim: Optional[str] = getattr(req, "series", None)
    measure: Optional[str] = req.measure
    aggregation: str = req.aggregation

    t = _unbound(table_name, columns)
    _validate(t, colnames, dimension, series_dim, measure, aggregation)
    t = _apply_filters(t, colnames, getattr(req, "filters", None))
    value = _agg_expr(t, measure, aggregation)
    limit = max(1, min(int(req.limit or DEFAULT_LIMIT), MAX_CATEGORIES))

    if dimension is None:
        # Scalar KPI -> SELECT <AGG> AS value FROM t
        expr = t.aggregate(value=value)
        sql = ibis.to_sql(expr, dialect="duckdb")
        logger.debug("aggregate KPI: %s", sql)
        rows = await db_manager.run_readwrite(sql)
        val = _jsonable(rows[0][0]) if rows else None
        return {
            "dimension": None,
            "series": None,
            "measure": measure,
            "aggregation": aggregation,
            "keys": [],
            "values": [val],
            "series_keys": [],
            "matrix": [],
            "compiled_sql": sql,
            "truncated": False,
        }

    # 2-D breakdown (TASK-025 / Wave 5): dimension x series -> matrix. Only when a
    # DISTINCT breakdown column is set -- series == dimension is a redundant no-op
    # and falls through to the 1-D grouped path below.
    if series_dim is not None and series_dim != dimension:
        return await _aggregate_2d(t, dimension, series_dim, measure, aggregation, value, limit)

    # Grouped series. A temporal dimension sorts by key ascending (a line chart
    # reads left-to-right in time); any other dimension sorts by the aggregated
    # value descending (biggest categories first), then caps at top-N.
    agg_t = t.group_by(dimension).aggregate(value=value)
    if t[dimension].type().is_temporal():
        ordered = agg_t.order_by(agg_t[dimension])
    else:
        ordered = agg_t.order_by(agg_t["value"].desc())
    expr = ordered.limit(limit)

    sql = ibis.to_sql(expr, dialect="duckdb")
    logger.debug("aggregate series: %s", sql)
    rows = await db_manager.run_readwrite(sql) or []

    # Compiled SELECT projects (dimension, value) in that order.
    keys = [_jsonable(r[0]) for r in rows]
    values = [_jsonable(r[1]) for r in rows]
    # Cheap heuristic: a full page almost certainly means more categories exist.
    truncated = len(rows) >= limit
    return {
        "dimension": dimension,
        "series": None,
        "measure": measure,
        "aggregation": aggregation,
        "keys": keys,
        "values": values,
        "series_keys": [],
        "matrix": [],
        "compiled_sql": sql,
        "truncated": truncated,
    }


async def _aggregate_2d(t, dimension, series_dim, measure, aggregation, value, limit):
    """The 2-D branch (TASK-025 / Wave 5): dimension x series -> matrix.

    Three compiled passes over the (already cross-filtered) table `t`:
      1. top-N primary keys -- same ordering rule as a 1-D series (temporal asc,
         else aggregated-value desc).
      2. top-M breakdown/series keys -- by aggregated magnitude, capped at MAX_SERIES
         (the breakdown is a legend, so it stays small regardless of `limit`).
      3. the grid -- filter to those keys on BOTH axes, GROUP BY [dimension, series],
         then pivot the (dim, series) -> value rows into matrix[i][j] in the client's
         keys[i] x series_keys[j] index order (missing cell => None).

    RAW (non-jsonable) key values feed the Pass-3 predicates so Ibis emits correctly
    typed literals (a DATE stays a date, never an ISO string); the jsonable forms are
    what the response returns. The aggregate is rebuilt on the filtered table in Pass 3
    because an Ibis aggregate must be rooted in the table it is grouped on.
    """
    # Pass 1: primary keys.
    agg_dim = t.group_by(dimension).aggregate(value=value)
    if t[dimension].type().is_temporal():
        ordered_dim = agg_dim.order_by(agg_dim[dimension])
    else:
        ordered_dim = agg_dim.order_by(agg_dim["value"].desc())
    sql1 = ibis.to_sql(ordered_dim.limit(limit), dialect="duckdb")
    dim_rows = await db_manager.run_readwrite(sql1) or []
    key_raw = [r[0] for r in dim_rows]
    key_order = [_jsonable(k) for k in key_raw]
    dim_truncated = len(dim_rows) >= limit

    # Pass 2: breakdown keys, by magnitude, top-M.
    agg_ser = t.group_by(series_dim).aggregate(value=value)
    ordered_ser = agg_ser.order_by(agg_ser["value"].desc())
    sql2 = ibis.to_sql(ordered_ser.limit(MAX_SERIES), dialect="duckdb")
    ser_rows = await db_manager.run_readwrite(sql2) or []
    series_raw = [r[0] for r in ser_rows]
    series_order = [_jsonable(s) for s in series_raw]
    series_truncated = len(ser_rows) >= MAX_SERIES

    header1 = "-- keys (top-N dimension)\n" + sql1
    header2 = "-- series (top-M breakdown)\n" + sql2

    # Empty table (no keys on either axis) -> empty grid, skip Pass 3.
    if not key_raw or not series_raw:
        return {
            "dimension": dimension,
            "series": series_dim,
            "measure": measure,
            "aggregation": aggregation,
            "keys": key_order,
            "values": [],
            "series_keys": series_order,
            "matrix": [],
            "compiled_sql": "\n\n".join([header1, header2]),
            "truncated": dim_truncated or series_truncated,
        }

    # Pass 3: the grid, restricted to the chosen keys on both axes.
    t2 = t.filter(_isin_pred(t[dimension], key_raw)).filter(_isin_pred(t[series_dim], series_raw))
    value2 = _agg_expr(t2, measure, aggregation)  # re-root the aggregate on t2
    grid = t2.group_by([dimension, series_dim]).aggregate(value=value2)
    sql3 = ibis.to_sql(grid, dialect="duckdb")
    logger.debug("aggregate 2-D grid: %s", sql3)
    grid_rows = await db_manager.run_readwrite(sql3) or []

    # Pivot (dimension, series, value) rows into matrix[i][j] in client index order.
    cell = {}
    for r in grid_rows:
        cell[(_jsonable(r[0]), _jsonable(r[1]))] = _jsonable(r[2])
    matrix = [[cell.get((k, s)) for s in series_order] for k in key_order]

    return {
        "dimension": dimension,
        "series": series_dim,
        "measure": measure,
        "aggregation": aggregation,
        "keys": key_order,
        "values": [],
        "series_keys": series_order,
        "matrix": matrix,
        "compiled_sql": "\n\n".join([header1, header2, "-- matrix (dimension x series)\n" + sql3]),
        "truncated": dim_truncated or series_truncated,
    }
