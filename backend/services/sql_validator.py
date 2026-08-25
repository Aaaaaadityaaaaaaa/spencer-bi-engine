"""SQL safety validation for AI-generated queries.

CRITICAL: this validator FAILS CLOSED. Every rejection path returns False.
The previous stub returned `True` unconditionally, meaning that the moment the
Phase 6 AI layer was wired up it would have approved literally any statement --
including `DROP TABLE` -- while looking like a functioning security control.
See CODING_STANDARDS.md AP-8 (a control that doesn't cover the path it claims).

This is defense layer 1 of 3 for AI SQL:
  1. this validator (statement must be a pure read)
  2. `run_sandboxed()` -- unconditional-rollback transaction (ADR-010)
  3. the human Review Gate in the UI
"""
import logging
from typing import Optional

import sqlglot
from sqlglot import exp

logger = logging.getLogger("spencer.sql_validator")

# Any of these appearing anywhere in the parsed tree disqualifies the statement.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Grant, exp.Attach, exp.Detach, exp.Copy,
    exp.Set, exp.Use, exp.Transaction, exp.Commit, exp.Rollback,
)

# DuckDB functions that read a file or an external data source. A pure analytical
# SELECT never needs these; on Spencer's shared single-file DuckDB they are the
# exfiltration surface -- read another tenant's upload, the .env, or the identity
# DB. A denylist (not an allowlist) because /execute must still allow the full
# analytical vocabulary (sum/date_trunc/regexp_*/...); the structural FROM check
# in scope_violation() is the backstop for any reader not named here.
_IO_FUNCTIONS = frozenset({
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan",
    "read_json", "read_json_auto", "read_ndjson", "read_json_objects",
    "read_text", "read_blob", "glob", "sniff_csv",
    "postgres_scan", "postgres_query", "sqlite_scan", "sqlite_query",
    "mysql_scan", "mysql_query", "iceberg_scan", "delta_scan",
    # metadata table-functions that would enumerate EVERY tenant's tables
    "duckdb_tables", "duckdb_columns", "duckdb_views", "duckdb_databases",
    "pragma_table_info", "pragma_database_list", "pragma_show_tables",
})


def _function_name(fn) -> str:
    """Best-effort lowercase name of a sqlglot function node, across versions.
    Anonymous stores the name in `.this` (a str); dedicated Func classes expose
    `sql_name()`."""
    if isinstance(fn, exp.Anonymous):
        this = fn.this
        return (this if isinstance(this, str) else (fn.name or "")).lower()
    try:
        return (fn.sql_name() or "").lower()
    except Exception:
        return (fn.name or "").lower()


class SQLValidator:
    def validate(self, sql: str) -> bool:
        """True only if `sql` is a single, pure read-only SELECT (optionally
        CTE-wrapped). Anything else -- unparseable, multi-statement, DDL, DML,
        or a write hidden inside a CTE -- returns False."""
        if not sql or not sql.strip():
            logger.warning("SQL rejected: empty")
            return False

        # Parse with the DuckDB dialect explicitly (CODING_STANDARDS.md).
        try:
            statements = sqlglot.parse(sql, read="duckdb")
        except Exception as exc:
            logger.warning("SQL rejected: parse failure (%s)", exc)
            return False

        statements = [s for s in statements if s is not None]

        # Reject statement stacking, e.g. "SELECT 1; DROP TABLE t".
        if len(statements) != 1:
            logger.warning("SQL rejected: expected 1 statement, got %d", len(statements))
            return False

        stmt = statements[0]

        # Top level must be a SELECT or a CTE-wrapped SELECT / set operation.
        if not isinstance(stmt, (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)):
            logger.warning("SQL rejected: top-level node is %s, not a SELECT", type(stmt).__name__)
            return False

        # Walk the whole tree: a write nested in a CTE or subquery is still a write.
        for node in stmt.walk():
            if isinstance(node, FORBIDDEN_NODES):
                logger.warning("SQL rejected: forbidden node %s", type(node).__name__)
                return False

        return True

    def scope_violation(self, sql: str, session_uuid: str) -> Optional[str]:
        """Return a reason string if `sql` reads ANYTHING outside session
        `session_uuid`'s own tables, else None. Assumes `validate(sql)` already
        passed (single pure read). This is the per-tenant gate for the /execute
        editor path (S-1, TASK-029): on the shared single-file DuckDB, "read-only"
        does NOT imply "only your own data" -- a bare SELECT can still read another
        tenant's table, or a file via read_csv_auto/read_text. Fails closed.

        Rules:
          1. every physical table reference must start with `t_<uuid>_` or
             `backup_<uuid>_`; CTE names defined in the statement are exempt, and
             any schema/catalog-qualified name (information_schema.*, otherdb.*)
             is rejected outright.
          2. no filesystem/external function anywhere in the tree, and no
             table-valued function as a FROM source (that reads an arbitrary file).
        """
        try:
            statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
        except Exception as exc:
            return f"could not be parsed ({exc})"
        if len(statements) != 1:
            return "must be a single statement"
        stmt = statements[0]

        uuid_ = session_uuid.replace("-", "_").lower()
        allowed_prefixes = (f"t_{uuid_}_", f"backup_{uuid_}_")
        cte_names = {(cte.alias_or_name or "").lower() for cte in stmt.find_all(exp.CTE)}

        # Rule 2: no file/external function calls anywhere in the tree.
        for fn in stmt.find_all(exp.Func):
            name = _function_name(fn)
            if name in _IO_FUNCTIONS:
                return f"uses the disallowed function '{name}()'"

        # Rule 1 (+ table-function backstop): inspect every table source.
        for tbl in stmt.find_all(exp.Table):
            inner = tbl.this
            if not isinstance(inner, exp.Identifier):
                label = getattr(inner, "name", None) or type(inner).__name__
                return f"reads from a table function ('{label}'), which is not allowed"
            if tbl.db or tbl.catalog:
                return f"references '{tbl.db or tbl.catalog}.{tbl.name}' outside this session"
            name = (tbl.name or "").lower()
            if name in cte_names:
                continue
            if not name.startswith(allowed_prefixes):
                return f"references table '{tbl.name}' outside this session"

        return None


sql_validator = SQLValidator()
