"""Wave 5 alias-resolution proof: users can write the ORIGINAL table name in the Query
Engine and it rewrites to the physical t_<uuid>_ name (AST-level) so the tenant-isolation
validator still passes. Standalone, Redis-free-ish (uses redis_manager with its fallback),
drives real spencer.db.

Run from a throwaway CWD:
    TMPD=$(mktemp -d) && cd "$TMPD" && python "E:/SPENCER V1/backend/test_alias.py"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.redis_manager import redis_manager
from services.duckdb_manager import db_manager
from services import alias_service
from services.sql_validator import sql_validator

UUID = "45076d77-9268-43c5-b104-fb10d963569a"
PHYS = f"t_{UUID.replace('-', '_')}_sales"
SCHEMA_KEY = f"schema:{UUID}"
_failures = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        _failures.append(label)
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


async def _teardown():
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{PHYS}"')
    redis_manager.client.delete(SCHEMA_KEY)


async def service_main():
    print("=" * 70)
    print("ALIAS RESOLUTION PROOF -- original table name -> physical t_<uuid>_ name")
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    print("=" * 70)

    await _teardown()
    await db_manager.run_readwrite(
        f'CREATE TABLE "{PHYS}" AS SELECT * FROM (VALUES (1, \'a\'), (2, \'b\')) AS t(id, region)'
    )
    # Seed the schema cache the resolver reads from.
    redis_manager.set_json(SCHEMA_KEY, {PHYS: {"is_primary": True, "cardinality": {}}})

    # --- 1. original name rewrites to physical ---------------------------------
    print("\n--- original name rewrites to physical ---")
    out =     await alias_service.resolve_aliases("SELECT * FROM sales", UUID)
    print(f"    -> {out}")
    check("output references physical name", PHYS.lower() in out.lower(), out)
    check("output no longer references bare 'sales'", " sales" not in out.lower().replace(PHYS.lower(), ""), out)
    check("scope validator passes on rewritten SQL", sql_validator.scope_violation(out, UUID) is None,
          str(sql_validator.scope_violation(out, UUID)))

    # --- 2. physical name already works (back-compat, no double rewrite) ------
    print("\n--- physical name is untouched ---")
    out2 =     await alias_service.resolve_aliases(f'SELECT region FROM "{PHYS}"', UUID)
    check("physical name preserved verbatim", PHYS.lower() in out2.lower(), out2)

    # --- 3. unknown name is left alone and still rejected by scope gate -------
    print("\n--- unknown name rejected as before ---")
    out3 =     await alias_service.resolve_aliases("SELECT * FROM not_mine", UUID)
    check("unknown name unchanged", "not_mine" in out3.lower(), out3)
    check("scope validator still rejects foreign table", sql_validator.scope_violation(out3, UUID) is not None,
          str(sql_validator.scope_violation(out3, UUID)))

    # --- 4. CTE / qualified refs untouched ------------------------------------
    print("\n--- CTE + qualified refs untouched ---")
    sql_cte = "WITH s AS (SELECT * FROM sales) SELECT * FROM s"
    out4 =     await alias_service.resolve_aliases(sql_cte, UUID)
    check("CTE body original rewritten", PHYS.lower() in out4.lower(), out4)
    check("CTE reference 's' unchanged", "FROM s" in out4, out4)
    sql_qual = "SELECT * FROM otherdb.sales"
    out5 =     await alias_service.resolve_aliases(sql_qual, UUID)
    check("qualified ref untouched", "otherdb.sales" in out5.lower(), out5)
    check("qualified ref still scope-rejected", sql_validator.scope_violation(out5, UUID) is not None,
          str(sql_validator.scope_violation(out5, UUID)))

    # --- 5. no matching table in the catalog -> original name unchanged ------
    print("\n--- no table in catalog -> unchanged ---")
    await db_manager.run_readwrite(f'DROP TABLE IF EXISTS "{PHYS}"')
    out6 =     await alias_service.resolve_aliases("SELECT * FROM sales", UUID)
    check("no table -> original name unchanged", "sales" in out6.lower(), out6)
    # Recreate so the teardown DROP below is a no-op-safe and earlier asserts stay valid.
    await db_manager.run_readwrite(
        f'CREATE TABLE "{PHYS}" AS SELECT * FROM (VALUES (1, \'a\'), (2, \'b\')) AS t(id, region)'
    )

    await _teardown()

    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} FAILURE(S): {_failures}")
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(service_main())
    sys.exit(1 if _failures else 0)
