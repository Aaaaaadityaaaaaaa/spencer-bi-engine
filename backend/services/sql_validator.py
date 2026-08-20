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

import sqlglot
from sqlglot import exp

logger = logging.getLogger("spencer.sql_validator")

# Any of these appearing anywhere in the parsed tree disqualifies the statement.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Grant, exp.Attach, exp.Detach, exp.Copy,
    exp.Set, exp.Use, exp.Transaction, exp.Commit, exp.Rollback,
)


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


sql_validator = SQLValidator()
