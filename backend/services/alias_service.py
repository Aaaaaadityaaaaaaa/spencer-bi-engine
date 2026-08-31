"""Wave 5 follow-up: original-table-name alias resolution for the Query Engine (user choice B).

Every physical DuckDB table is namespaced `t_<session_uuid>_<original>` for uniqueness +
tenant isolation (the SQL validator only permits `t_<uuid>_` / `backup_<uuid>_` references,
so a query on the shared single-file DuckDB can never read another session's data). That
makes the *real* name long and ugly, and forces the user to type it in the Query Engine.

This module lets the user write/see the short ORIGINAL name instead. `resolve_aliases`
rewrites original-name references to the physical name at the **SQL AST level** (sqlglot),
never via string interpolation, and only for identifiers that match a session table. The
tenant-isolation validator then runs on the rewritten (physical) names exactly as before,
so the security boundary is unchanged. Names that don't match a session table are left
untouched and fall through to the validator as usual.

The alias map is derived from the LIVE DuckDB catalog (`duckdb_tables()`), filtered by the
session's `t_<uuid>_` prefix -- the catalog is the source of truth, so this works even if the
Redis schema cache is stale or absent for the session.
"""
from typing import Dict
import sqlglot
from sqlglot import exp

from services.duckdb_manager import db_manager


async def _alias_map(session_uuid: str) -> Dict[str, str]:
    """original(lower) -> physical for this session's tables, from the live catalog."""
    uuid_ = session_uuid.replace("-", "_").lower()
    prefix = f"t_{uuid_}_"
    try:
        rows = await db_manager.run_readwrite(
            "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE ?",
            (prefix + "%",),
        )
    except Exception:
        return {}
    aliases: Dict[str, str] = {}
    for row in (rows or []):
        physical = row[0]
        if isinstance(physical, str) and physical.startswith(prefix):
            original = physical[len(prefix):]
            if original:
                aliases[original.lower()] = physical
    return aliases


async def resolve_aliases(sql: str, session_uuid: str) -> str:
    """Rewrite original table-name references in `sql` to their physical `t_<uuid>_` names.

    AST-level only; CTE names, schema-qualified refs and table functions are left alone so
    the validator keeps owning those cases. Returns the SQL unchanged if it cannot be parsed
    (the validator will then reject it) or if the session has no tables."""
    aliases = await _alias_map(session_uuid)
    if not aliases:
        return sql
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return sql
    if tree is None:
        return sql
    for tbl in tree.find_all(exp.Table):
        inner = tbl.this
        if not isinstance(inner, exp.Identifier):
            continue  # table function / non-identifier source -> leave for validator
        if tbl.db or tbl.catalog:
            continue  # qualified name -> leave for validator
        physical = aliases.get((tbl.name or "").lower())
        if physical and physical != tbl.name:
            tbl.set("this", exp.to_identifier(physical, quoted=inner.quoted))
    return tree.sql(dialect="duckdb")
