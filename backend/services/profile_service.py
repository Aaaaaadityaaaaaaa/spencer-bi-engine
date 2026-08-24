"""Column profiler for the Table data-prep workspace (TASK-015).

Given one column, compute a compact statistical profile: completeness (null %,
distinct count) plus kind-appropriate detail -- numeric -> min/max/mean/median/
std + a fixed-bin histogram; temporal -> min/max + most-frequent values;
categorical/boolean -> most-frequent values.

Like ``aggregate_service`` (Phase 5), every query is built as an **Ibis
expression on an unbound table** and compiled to DuckDB SQL text (Ibis is a
compiler here -- it never opens its own connection), then executed through the
existing ``db_manager.run_readwrite`` wrapper.

Only the column NAME travels from the client; it is validated against the LIVE
schema (fresh PRAGMA per request via the shared ``_columns_of``, never cached --
a transform can add/drop/rename/retype a column) before Ibis builds anything, so
no client value is interpolated into SQL (ADR-012). The histogram's bin bounds
are SERVER-computed floats (derived from the column's own MIN/MAX), carried as
typed Ibis literals -- never client input. Single-table only (ADR-006); the
router resolves the table.

This deliberately reuses ``transform_service``'s hard-won helpers (the
unbound-table builder + the fresh column fetch) and ``aggregate_service``'s
scalar-coercion helper rather than duplicating them.
"""

import logging
from typing import Any, Dict, List, Optional

import ibis

from services.duckdb_manager import db_manager
from services.transform_service import _unbound, _columns_of  # noqa: F401 (reused helpers)
from services.aggregate_service import _jsonable  # canonical DuckDB-scalar -> JSON coercion

logger = logging.getLogger("spencer.profile")

# Most-frequent values returned for a categorical / temporal / boolean column.
TOP_N = 20
# Fixed bin count for the numeric histogram. A constant so bin math is predictable
# and the response size is bounded regardless of the column's range/cardinality.
HIST_BINS = 10


class ProfileError(Exception):
    """User-input problem (unknown column). The router maps this to HTTP 400,
    not 500 -- it is not a server bug."""


def _kind_of(dtype) -> str:
    """Classify a column for profiling. Boolean is checked out of `is_numeric`
    explicitly (some engines treat bool as numeric) so it profiles as a two-value
    category, not as a histogram."""
    if dtype.is_boolean():
        return "boolean"
    if dtype.is_numeric():
        return "numeric"
    if dtype.is_temporal():
        return "temporal"
    return "categorical"


def _num_or_none(v: Any) -> Optional[float]:
    """Coerce a numeric scalar (int / float / Decimal) to float; None stays None.
    Used for mean/median/std and the histogram bounds, which are always numbers."""
    return None if v is None else float(v)


async def profile_column(table_name: str, column: str) -> Dict[str, Any]:
    """Profile one column of a session table. Returns a plain dict matching
    ColumnProfile. Raises ProfileError (-> 400) for an unknown column."""
    columns = await _columns_of(table_name)  # fresh schema, never cached
    if not columns:
        raise ProfileError(f"table '{table_name}' has no columns or does not exist")
    coltypes = {name: dtype for name, dtype in columns}
    if column not in coltypes:
        raise ProfileError(f"column '{column}' not found")

    raw_type = coltypes[column]
    t = _unbound(table_name, columns)
    col = t[column]
    kind = _kind_of(col.type())

    sqls: List[str] = []

    # --- Query 1: one scalar row of stats -----------------------------------
    # Completeness always; min/max for anything orderable (numeric/temporal);
    # mean/median/std only where they are defined (numeric).
    aggs: Dict[str, Any] = {
        "total": t.count(),
        "non_null": col.count(),   # COUNT(col) excludes NULLs
        "distinct": col.nunique(),  # COUNT(DISTINCT col), NULLs excluded
    }
    if kind in ("numeric", "temporal"):
        aggs["min"] = col.min()
        aggs["max"] = col.max()
    if kind == "numeric":
        aggs["mean"] = col.mean()
        aggs["median"] = col.median()
        aggs["std"] = col.std()

    stats_expr = t.aggregate(**aggs)
    stats_sql = ibis.to_sql(stats_expr, dialect="duckdb")
    sqls.append(stats_sql)
    srow = await db_manager.run_readwrite(stats_sql)
    # Zip by the kwargs key order (dict + **kwargs both preserve insertion order),
    # so this is robust regardless of the compiled SELECT's column ordering.
    stats = dict(zip(list(aggs.keys()), srow[0])) if srow else {k: None for k in aggs}

    total = int(stats.get("total") or 0)
    non_null = int(stats.get("non_null") or 0)
    distinct = int(stats.get("distinct") or 0)
    null_count = max(0, total - non_null)
    null_pct = round((null_count / total) * 100, 2) if total else 0.0

    result: Dict[str, Any] = {
        "column": column,
        "type": raw_type,
        "kind": kind,
        "total": total,
        "non_null": non_null,
        "null_count": null_count,
        "null_pct": null_pct,
        "distinct": distinct,
        "min": _jsonable(stats.get("min")),
        "max": _jsonable(stats.get("max")),
        "mean": _num_or_none(stats.get("mean")),
        "median": _num_or_none(stats.get("median")),
        "std": _num_or_none(stats.get("std")),
        "histogram": [],
        "top_values": [],
    }

    # --- Query 2a (numeric): fixed-bin histogram ----------------------------
    if kind == "numeric" and non_null > 0:
        lo = _num_or_none(stats.get("min"))
        hi = _num_or_none(stats.get("max"))
        if lo is not None and hi is not None:
            if hi <= lo:
                # Every non-null value is identical -> one bin, no query needed
                # (also dodges a divide-by-zero on the bin width).
                result["histogram"] = [{"x0": lo, "x1": hi, "count": non_null}]
            else:
                width = (hi - lo) / HIST_BINS
                tf = t.filter(col.notnull())
                colf = tf[column]
                # Bin index = floor((value - lo) / width), clamped so the max value
                # (which would land at index HIST_BINS) folds into the last bin.
                # lo/width are server-computed literals, never client input.
                bin_idx = (
                    ((colf - lo) / width)
                    .floor()
                    .clip(lower=0, upper=HIST_BINS - 1)
                    .cast("int64")
                    .name("bin")
                )
                hgrouped = tf.group_by(bin_idx).aggregate(count=tf.count())
                hexpr = hgrouped.order_by(hgrouped["bin"])
                hist_sql = ibis.to_sql(hexpr, dialect="duckdb")
                sqls.append(hist_sql)
                hrows = await db_manager.run_readwrite(hist_sql) or []
                counts = {int(r[0]): int(r[1]) for r in hrows if r[0] is not None}
                bins: List[Dict[str, Any]] = []
                for i in range(HIST_BINS):
                    x0 = lo + i * width
                    x1 = hi if i == HIST_BINS - 1 else lo + (i + 1) * width
                    bins.append({"x0": x0, "x1": x1, "count": counts.get(i, 0)})
                result["histogram"] = bins

    # --- Query 2b (categorical/temporal/boolean): most-frequent values ------
    elif kind in ("categorical", "temporal", "boolean") and non_null > 0:
        tf = t.filter(col.notnull())
        grouped = tf.group_by(column).aggregate(count=tf.count())
        # Value DESC by frequency; the group key as a stable ASC tiebreak so equal
        # counts return in a deterministic order.
        ordered = grouped.order_by([grouped["count"].desc(), grouped[column]])
        tv_expr = ordered.limit(TOP_N)
        tv_sql = ibis.to_sql(tv_expr, dialect="duckdb")
        sqls.append(tv_sql)
        trows = await db_manager.run_readwrite(tv_sql) or []
        result["top_values"] = [
            {"value": _jsonable(r[0]), "count": int(r[1])} for r in trows
        ]

    result["compiled_sql"] = ";\n\n".join(sqls)
    logger.debug("profile %s.%s (%s)", table_name, column, kind)
    return result
