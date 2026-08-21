"""Phase 3 data-cleaning transforms (TASK-004, extended in TASK-005).

Design (ADR-007, ADR-004, ADR-014/015, ARCHITECTURE.md):
- Structured ops (dedupe, drop_null, impute, cast, and the TASK-005 additions
  drop_column / rename_column / dedupe_subset / string_normalize) are built as
  **Ibis expressions on an unbound table** and compiled to DuckDB SQL text. Ibis
  never opens its own connection here -- it is a compiler only. The compiled
  SELECT is executed through the existing ``db_manager.run_readwrite`` wrapper.
- ``calculated_column`` (a value expression) and ``filter_rows`` (a boolean
  predicate) cannot go through Ibis -- both are free-form user SQL. They share a
  single fail-closed sqlglot validator (``_validate_formula``): a single pure
  scalar expression, no statement/subquery/write node anywhere in its tree, only
  existing columns, and only functions on an explicit allowlist (ADR-015 closes
  the ADR-014 function-allowlist residual). This is the same fail-closed
  philosophy as ``sql_validator`` (ADR-013), because both run on the
  non-sandboxed ``run_readwrite`` path with no rollback protection (cf. ADR-012).
- Undo/redo uses materialized full-table snapshots ``backup_{table}_step_{n}``
  capped at SNAPSHOT_CAP (ADR-004), not CTE chaining. Every state is a real,
  inspectable table.
- ``preview_transform`` dry-runs an op via read-only SELECTs only -- no
  materialize, snapshot, history entry, or schema_version bump (TASK-005).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import asyncio

import ibis
import sqlglot
from sqlglot import exp

from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager

logger = logging.getLogger("spencer.transform")

SNAPSHOT_CAP = 10  # ADR-004: keep the last 5-10 states; drop oldest on overflow.

# State-mutating ops (apply/undo/redo) are serialized per (session, table) so an
# overlapping pair can't interleave their read-modify-write of history or race on
# the temp-swap table. The app runs --workers 1, so a process-local asyncio lock
# is sufficient (there is no second process to coordinate with).
_locks: Dict[str, asyncio.Lock] = {}


def _lock_for(session_uuid: str, table_name: str) -> asyncio.Lock:
    key = f"{session_uuid}:{table_name}"
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock

# --- DuckDB type string -> Ibis dtype -------------------------------------
# Ibis's own DuckDB parser understands every DuckDB alias (BIGINT->int64,
# HUGEINT->decimal(38,0), ...). Guard the internal import path with a small
# fallback map so a future Ibis refactor degrades gracefully rather than crashing.
try:
    from ibis.backends.sql.datatypes import DuckDBType

    def _ibis_dtype(duckdb_type: str):
        return DuckDBType.from_string(duckdb_type)
except Exception:  # pragma: no cover - defensive
    _FALLBACK = {
        "BIGINT": "int64", "INT8": "int64", "LONG": "int64",
        "INTEGER": "int32", "INT": "int32", "INT4": "int32",
        "SMALLINT": "int16", "INT2": "int16",
        "TINYINT": "int8", "INT1": "int8",
        "UBIGINT": "uint64", "UINTEGER": "uint32", "USMALLINT": "uint16", "UTINYINT": "uint8",
        "HUGEINT": "decimal(38, 0)",
        "DOUBLE": "float64", "FLOAT8": "float64",
        "FLOAT": "float32", "REAL": "float32", "FLOAT4": "float32",
        "VARCHAR": "string", "CHAR": "string", "TEXT": "string", "STRING": "string",
        "BOOLEAN": "boolean", "BOOL": "boolean",
        "DATE": "date", "TIMESTAMP": "timestamp", "TIME": "time",
        "BLOB": "binary", "UUID": "string",
    }

    def _ibis_dtype(duckdb_type: str):
        key = duckdb_type.upper().strip()
        if key.startswith("DECIMAL"):
            return ibis.dtype(duckdb_type.lower())
        return ibis.dtype(_FALLBACK.get(key, "string"))


class TransformError(Exception):
    """Raised for user-input problems (bad formula, unknown column, bad type).
    Endpoints map this to HTTP 400, not 500 -- it is not a server bug."""


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snap_name(table_name: str, state_id: int) -> str:
    return f"backup_{table_name}_step_{state_id}"


def _history_key(session_uuid: str, table_name: str) -> str:
    return f"history:{session_uuid}:{table_name}"


def _get_history(session_uuid: str, table_name: str) -> Dict[str, Any]:
    return redis_manager.get_json(_history_key(session_uuid, table_name)) or {
        "entries": [], "current": -1, "next_id": 0,
    }


def _set_history(session_uuid: str, table_name: str, hist: Dict[str, Any]) -> None:
    redis_manager.set_json(_history_key(session_uuid, table_name), hist)


async def _columns_of(table_name: str) -> List[Tuple[str, str]]:
    info = await db_manager.run_readwrite(f"PRAGMA table_info({table_name})")
    return [(row[1], row[2]) for row in (info or [])]


async def _snapshot(table_name: str, snap: str) -> None:
    await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {snap}")
    await db_manager.run_readwrite(f"CREATE TABLE {snap} AS SELECT * FROM {table_name}")


async def _restore(table_name: str, snap: str) -> None:
    await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {table_name}")
    await db_manager.run_readwrite(f"CREATE TABLE {table_name} AS SELECT * FROM {snap}")


async def _materialize(select_sql: str, table_name: str, token: int) -> None:
    """Replace ``table_name`` with the result of ``select_sql`` via a temp swap.
    The user-influenced SQL runs in the FIRST step (create tmp); if it fails, the
    live table is never dropped, so a bad transform can't destroy data. ``token``
    (the new state id) makes the temp name unique so it can't collide."""
    tmp = f"{table_name}__tmp_{token}"
    await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {tmp}")
    try:
        await db_manager.run_readwrite(f"CREATE TABLE {tmp} AS {select_sql}")
    except Exception as exc:
        await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {tmp}")
        raise TransformError(f"transform could not be applied: {exc}") from exc
    await db_manager.run_readwrite(f"DROP TABLE {table_name}")
    await db_manager.run_readwrite(f"ALTER TABLE {tmp} RENAME TO {table_name}")


# --- op compilation --------------------------------------------------------

def _unbound(table_name: str, columns: List[Tuple[str, str]]):
    schema = {name: _ibis_dtype(dtype) for name, dtype in columns}
    return ibis.table(schema, name=table_name)


def _compile_structured(table_name: str, columns: List[Tuple[str, str]], param) -> str:
    """Build the Ibis expression for a structured op and compile to DuckDB SQL."""
    colnames = {c for c, _ in columns}
    t = _unbound(table_name, columns)
    op = param.op

    if op == "dedupe":
        expr = t.distinct()

    elif op == "drop_null":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        expr = t.filter(t[param.column].notnull())

    elif op == "impute_null":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        col = t[param.column]
        strat = param.strategy
        if strat == "zero":
            fill = ibis.literal(0)
        elif strat == "mean":
            fill = col.mean()
        elif strat == "median":
            fill = col.median()
        elif strat == "mode":
            # Most-frequent non-null value. Ibis compiles this to a MODE(...) OVER
            # (full frame) so it also works for a categorical/text column, where
            # mean/median are undefined (TASK-005).
            fill = col.mode()
        elif strat == "custom":
            if param.fill_value is None:
                raise TransformError("impute strategy 'custom' requires fill_value")
            fill = ibis.literal(param.fill_value)
        else:
            raise TransformError(f"unknown impute strategy '{strat}'")
        expr = t.mutate(**{param.column: col.fill_null(fill)})

    elif op == "cast":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        try:
            target = _ibis_dtype(param.new_type)
        except Exception as exc:
            raise TransformError(f"'{param.new_type}' is not a valid DuckDB type") from exc
        expr = t.mutate(**{param.column: t[param.column].cast(target)})

    elif op == "drop_column":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        if len(colnames) <= 1:
            raise TransformError("cannot drop the only remaining column")
        expr = t.drop(param.column)

    elif op == "rename_column":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        new = (param.new_name or "").strip()
        if not new:
            raise TransformError("new column name is empty")
        if new == param.column:
            raise TransformError("new name equals the current name")
        if new in colnames:
            raise TransformError(f"column '{new}' already exists")
        # Ibis rename direction is {new: old}; it quotes both identifiers itself.
        expr = t.rename({new: param.column})

    elif op == "dedupe_subset":
        subset = list(param.columns or [])
        if not subset:
            raise TransformError("dedupe_subset requires at least one column")
        unknown = [c for c in subset if c not in colnames]
        if unknown:
            raise TransformError(f"dedupe_subset references unknown column(s): {unknown}")
        # Ibis distinct(on, keep) -> GROUP BY <subset>, taking the first/last
        # *non-null* value of each other column per group (DuckDB group order is
        # not guaranteed -- this collapses to one row per key, it is not a stable
        # "keep the original first row wholesale"). Documented in ADR-015.
        expr = t.distinct(on=subset, keep=param.keep)

    elif op == "string_normalize":
        if param.column not in colnames:
            raise TransformError(f"column '{param.column}' not found")
        coltypes = {c: d for c, d in columns}
        dt = coltypes.get(param.column, "").upper()
        if not ("CHAR" in dt or "TEXT" in dt or "STRING" in dt):
            raise TransformError(
                f"string_normalize needs a text column; '{param.column}' is {dt or 'unknown'}"
            )
        col = t[param.column]
        applied = False
        if param.trim:
            col = col.strip()
            applied = True
        if param.case:
            if param.case == "upper":
                col = col.upper()
            elif param.case == "lower":
                col = col.lower()
            elif param.case == "capitalize":
                # First character upper, rest lower (whole string). Per-word
                # "title case" is intentionally not offered -- the engine has no
                # per-word initcap; documented honestly in ADR-015.
                col = col.capitalize()
            else:
                raise TransformError(f"unknown case '{param.case}'")
            applied = True
        if param.find is not None:
            col = col.replace(param.find, param.replace or "")
            applied = True
        if param.null_token is not None:
            col = col.nullif(param.null_token)
            applied = True
        if not applied:
            raise TransformError("string_normalize requires at least one operation")
        expr = t.mutate(**{param.column: col})

    else:
        raise TransformError(f"unsupported structured op '{op}'")

    return ibis.to_sql(expr, dialect="duckdb")


# --- calculated column: fail-closed formula validation ---------------------

# A calculated-column formula is a scalar expression. Anything that could be a
# statement, a subquery, or a write is rejected outright (same class of control
# as sql_validator / ADR-012, since this runs on the non-sandboxed path).
_FORBIDDEN_FORMULA_NODES = (
    exp.Select, exp.Subquery, exp.Union, exp.Insert, exp.Update, exp.Delete,
    exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Into, exp.Set,
    exp.Semicolon,
)

# ADR-014 recorded a residual: the validator rejected statements/subqueries/writes
# and unknown columns but did NOT whitelist scalar *functions*. TASK-005 (ADR-015)
# closes it. A scalar expression may only call functions on this explicit list;
# anything else -- I/O (read_csv_auto/read_parquet), sequence mutation (nextval),
# sleeps (pg_sleep), or any unrecognized built-in -- is rejected. This gates BOTH
# the calculated_column formula and the filter_rows predicate (one shared validator).
_ALLOWED_FUNCTIONS = frozenset({
    # logical connectives -- sqlglot models AND/OR/NOT as exp.Func subclasses
    "AND", "OR", "NOT",
    # null / conditional
    "COALESCE", "NULLIF", "IFNULL", "IF", "IIF", "CASE", "GREATEST", "LEAST",
    # math
    "ABS", "ROUND", "CEIL", "CEILING", "FLOOR", "SQRT", "CBRT", "POWER", "POW",
    "EXP", "LN", "LOG", "LOG2", "LOG10", "MOD", "SIGN", "TRUNC",
    # string
    "UPPER", "LOWER", "TRIM", "LTRIM", "RTRIM", "LENGTH", "LEN", "SUBSTR",
    "SUBSTRING", "REPLACE", "CONCAT", "CONCAT_WS", "LEFT", "RIGHT", "LPAD",
    "RPAD", "REVERSE", "CONTAINS", "STARTS_WITH", "ENDS_WITH", "SPLIT_PART",
    "INITCAP", "REGEXP_REPLACE", "REGEXP_EXTRACT", "REGEXP_MATCHES",
    # type conversion -- CAST parses to exp.Cast, itself a Func subclass
    "CAST", "TRY_CAST",
    # date/time (pure scalar)
    "DATE_PART", "DATE_TRUNC", "DATE_DIFF", "EXTRACT", "STRFTIME", "STRPTIME",
    "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "DAYOFWEEK", "DAYOFYEAR",
})


def _func_name(node) -> str:
    """Canonical upper-case name of a sqlglot Func node. Unknown/arbitrary calls
    parse to exp.Anonymous, whose sql_name() is the useless literal 'ANONYMOUS' --
    their real name lives in .name; known typed funcs expose it via sql_name().
    The class-name fallback still yields the canonical name for typed funcs
    (Abs->ABS) and, being fail-closed, only ever errs toward rejection."""
    if isinstance(node, exp.Anonymous):
        return (node.name or "").upper()
    try:
        return node.sql_name().upper()
    except Exception:  # pragma: no cover - defensive
        return type(node).__name__.upper()


def _validate_formula(formula: str, allowed_columns: set) -> str:
    """Return a normalized, safe scalar-expression SQL string, or raise.
    Fail-closed: any parse error, statement, subquery, write node, unknown column
    reference, or non-allowlisted function call is rejected. Shared by
    calculated_column (a value expression) and filter_rows (a boolean predicate)."""
    if not formula or not formula.strip():
        raise TransformError("expression is empty")
    try:
        statements = sqlglot.parse(formula, dialect="duckdb")
    except Exception as exc:
        raise TransformError(f"expression does not parse: {exc}") from exc
    if len(statements) != 1 or statements[0] is None:
        raise TransformError("expression must be a single scalar expression")
    tree = statements[0]
    # A bare scalar expression must not itself be a statement/command node.
    if isinstance(tree, _FORBIDDEN_FORMULA_NODES):
        raise TransformError("expression must be a scalar expression, not a statement")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_FORMULA_NODES):
            raise TransformError("expression may not contain subqueries or write statements")
        if isinstance(node, exp.Func):
            fname = _func_name(node)
            if fname not in _ALLOWED_FUNCTIONS:
                raise TransformError(f"function '{fname}' is not allowed")
    referenced = {c.name for c in tree.find_all(exp.Column)}
    unknown = referenced - allowed_columns
    if unknown:
        raise TransformError(f"expression references unknown column(s): {sorted(unknown)}")
    return tree.sql(dialect="duckdb")


def _build_calc_sql(table_name: str, columns: List[Tuple[str, str]], param) -> str:
    colnames = {c for c, _ in columns}
    if param.new_column_name in colnames:
        raise TransformError(f"column '{param.new_column_name}' already exists")
    safe = _validate_formula(param.formula, colnames)
    newcol = _quote_ident(param.new_column_name)
    return f"SELECT *, ({safe}) AS {newcol} FROM {table_name}"


def _build_filter_sql(table_name: str, columns: List[Tuple[str, str]], param) -> str:
    """filter_rows: keep/remove rows matching a user predicate.
    SECURITY: the predicate is user SQL on the non-sandboxed path, so it reuses the
    SAME fail-closed validator (+ function allowlist) as calculated_column -- there
    is deliberately no second, weaker predicate-validation path (ADR-015)."""
    colnames = {c for c, _ in columns}
    safe = _validate_formula(param.predicate, colnames)
    if param.action == "keep":
        where = f"({safe})"
    elif param.action == "remove":
        where = f"NOT ({safe})"
    else:
        raise TransformError("filter action must be 'keep' or 'remove'")
    return f"SELECT * FROM {table_name} WHERE {where}"


def _compile_op(table_name: str, columns: List[Tuple[str, str]], param) -> str:
    """Compile any transform op to a single DuckDB SELECT string. Shared by
    apply_transform and preview_transform so both paths validate identically."""
    if param.op == "calculated_column":
        return _build_calc_sql(table_name, columns, param)
    if param.op == "filter_rows":
        return _build_filter_sql(table_name, columns, param)
    return _compile_structured(table_name, columns, param)


# --- public API ------------------------------------------------------------

async def apply_transform(session_uuid: str, table_name: str, param) -> Tuple[int, int, int]:
    """Apply one transform op; returns (schema_version, current_step_index, row_count)."""
    async with _lock_for(session_uuid, table_name):
        columns = await _columns_of(table_name)
        if not columns:
            raise TransformError(f"table '{table_name}' not found")

        hist = _get_history(session_uuid, table_name)

        # Initialize state 0 = pristine snapshot the first time this table is touched.
        if not hist["entries"]:
            await _snapshot(table_name, _snap_name(table_name, 0))
            hist = {
                "entries": [{"state_id": 0, "op": "initial", "column": None, "timestamp": _now()}],
                "current": 0,
                "next_id": 1,
            }
        else:
            # A new transform after an undo discards the redo branch.
            await _drop_redo_branch(table_name, hist)

        select_sql = _compile_op(table_name, columns, param)

        new_id = hist["next_id"]
        hist["next_id"] = new_id + 1
        await _materialize(select_sql, table_name, new_id)
        await _snapshot(table_name, _snap_name(table_name, new_id))
        hist["entries"].append({
            "state_id": new_id,
            "op": param.op,
            "column": getattr(param, "column", None) or getattr(param, "new_column_name", None),
            "timestamp": _now(),
        })
        hist["current"] = len(hist["entries"]) - 1

        await _enforce_cap(table_name, hist)
        _set_history(session_uuid, table_name, hist)

        version = redis_manager.incr_version(session_uuid)
        row_count = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {table_name}"))[0][0]
        return version, hist["current"], row_count


async def preview_transform(session_uuid: str, table_name: str, param, sample_limit: int = 20) -> Dict[str, Any]:
    """Dry-run an op: compile its SELECT and report the row-count delta, resulting
    schema, and a small sample -- all via read-only SELECTs. Deliberately does NOT
    lock, materialize, snapshot, add a history entry, or bump schema_version, so a
    preview can never change committed state (TASK-005 req 7). The same fail-closed
    validator runs here as in apply, so a malicious formula/predicate is rejected
    identically at preview time."""
    columns = await _columns_of(table_name)
    if not columns:
        raise TransformError(f"table '{table_name}' not found")

    select_sql = _compile_op(table_name, columns, param)

    before = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {table_name}"))[0][0]
    try:
        after = (await db_manager.run_readwrite(
            f"SELECT COUNT(*) FROM ({select_sql}) AS _pv"))[0][0]
        # DESCRIBE gives the RESULT schema (post-op) without materializing anything.
        desc = await db_manager.run_readwrite(f"DESCRIBE {select_sql}")
        rows = await db_manager.run_readwrite(
            f"SELECT * FROM ({select_sql}) AS _pv LIMIT {int(sample_limit)}")
    except Exception as exc:
        raise TransformError(f"preview could not be computed: {exc}") from exc

    col_names = [r[0] for r in (desc or [])]
    col_types = [r[1] for r in (desc or [])]
    sample = [dict(zip(col_names, row)) for row in (rows or [])]

    return {
        "op": param.op,
        "row_count_before": before,
        "row_count_after": after,
        "row_count_delta": after - before,
        "columns": [{"name": n, "type": t} for n, t in zip(col_names, col_types)],
        "sample": sample,
        "compiled_sql": select_sql,
    }


async def undo(session_uuid: str, table_name: str) -> Tuple[int, int, int]:
    async with _lock_for(session_uuid, table_name):
        hist = _get_history(session_uuid, table_name)
        if hist["current"] <= 0:
            raise TransformError("nothing to undo")
        hist["current"] -= 1
        state_id = hist["entries"][hist["current"]]["state_id"]
        await _restore(table_name, _snap_name(table_name, state_id))
        _set_history(session_uuid, table_name, hist)
        version = redis_manager.incr_version(session_uuid)
        row_count = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {table_name}"))[0][0]
        return version, hist["current"], row_count


async def redo(session_uuid: str, table_name: str) -> Tuple[int, int, int]:
    async with _lock_for(session_uuid, table_name):
        hist = _get_history(session_uuid, table_name)
        if hist["current"] >= len(hist["entries"]) - 1:
            raise TransformError("nothing to redo")
        hist["current"] += 1
        state_id = hist["entries"][hist["current"]]["state_id"]
        await _restore(table_name, _snap_name(table_name, state_id))
        _set_history(session_uuid, table_name, hist)
        version = redis_manager.incr_version(session_uuid)
        row_count = (await db_manager.run_readwrite(f"SELECT COUNT(*) FROM {table_name}"))[0][0]
        return version, hist["current"], row_count


def get_history(session_uuid: str, table_name: str) -> Dict[str, Any]:
    hist = _get_history(session_uuid, table_name)
    entries = hist["entries"]
    current = hist["current"]
    steps = [
        {"step": i, "op": e["op"], "column": e.get("column"), "timestamp": e["timestamp"]}
        for i, e in enumerate(entries)
    ]
    return {
        "steps": steps,
        "current_step_index": current,
        "total_steps": len(entries),
        "can_undo": current > 0,
        "can_redo": current < len(entries) - 1,
    }


async def _drop_redo_branch(table_name: str, hist: Dict[str, Any]) -> None:
    cur = hist["current"]
    for e in hist["entries"][cur + 1:]:
        await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_snap_name(table_name, e['state_id'])}")
    hist["entries"] = hist["entries"][: cur + 1]


async def _enforce_cap(table_name: str, hist: Dict[str, Any]) -> None:
    while len(hist["entries"]) > SNAPSHOT_CAP:
        oldest = hist["entries"].pop(0)
        await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_snap_name(table_name, oldest['state_id'])}")
        hist["current"] -= 1
