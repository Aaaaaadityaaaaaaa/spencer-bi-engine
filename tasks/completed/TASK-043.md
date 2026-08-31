# TASK-043 — Original table name in the Query Engine (alias resolution)

## Summary
Every physical DuckDB table is namespaced `t_<session_uuid>_<original>` for uniqueness + tenant
isolation on the single shared `spencer.db` file. That makes the real name long and ugly
(`t_45076d77_9268_43c5_b104_fb10d963569a_messy_sales_dataset_100k`) and forces the user to type
it in the Query Engine. The user chose option **(B)**: let them write/see the short ORIGINAL name
everywhere, with the backend rewriting it to the physical name at the SQL AST level before the
tenant-isolation validator runs. The security boundary is unchanged — the validator still sees
only physical `t_<uuid>_` names.

## Acceptance Criteria
- [x] A query typed with the original table name (`SELECT * FROM messy_sales_dataset_100k`) runs and resolves to the physical `t_<uuid>_` table.
- [x] Rewriting is AST-level (sqlglot), not string interpolation — no injection surface; CTE names, schema-qualified refs and table functions are left for the validator.
- [x] The tenant-isolation validator still runs on the rewritten physical names and rejects foreign/unprefixed tables exactly as before.
- [x] Physical names already in SQL pass through untouched (back-compat); AI-generated SQL (which uses physical names) is unaffected.
- [x] UI shows the original name in the table switcher and the Query Engine header; the "insert table name" token drops the short name into the editor.

## Files changed
- `backend/services/alias_service.py` (new) — `_alias_map` (derives original→physical from the `schema:{session_uuid}` cache) + `resolve_aliases` (sqlglot AST rewrite).
- `backend/routers/ai.py` — `execute_query` calls `alias_service.resolve_aliases(sql, session_uuid)` before `validate`/`scope_violation`. This is the single execution point for manual SQL and all AI-generated SQL (Review Gate), so both paths are covered.
- `frontend/src/utils/tableName.ts` — added `displayTableName(physical, sessionUuid)` (restored existing `friendlyTableName`).
- `frontend/src/components/TableSwitcher.vue` — shows `displayTableName(...)`; tooltip keeps the real physical name.
- `frontend/src/components/QueryConsole.vue` — header chip shows the original name; "insert table name" token now inserts the short name (backend resolves it).

## Important implementation decisions
- **Derive, don't store:** the alias map is computed from the existing `schema:{session_uuid}` Redis cache (each key is a physical name with the `t_<uuid>_` prefix); no new storage or schema change.
- **AST-level rewrite:** `resolve_aliases` parses with sqlglot, replaces only `exp.Table` identifiers whose name matches a session original (case-insensitive), and re-serializes. This is strictly safer than string replacement and cannot be abused to inject.
- **Security preserved:** rewriting happens *before* `sql_validator.validate` + `scope_violation`, so the validator still operates on physical names and the multi-tenant gate is intact. An unknown original name is left as-is and still rejected by the validator (verified in tests).
- The Query Console previously imported `friendlyTableName` from `utils/tableName.ts`; that function was preserved so no regression.

## Tests executed + actual results
Backend proof `test_alias.py` (standalone, drives real spencer.db + Redis):

```
--- original name rewrites to physical ---
  [PASS] output references physical name
  [PASS] scope validator passes on rewritten SQL
--- physical name is untouched ---
  [PASS] physical name preserved verbatim
--- unknown name rejected as before ---
  [PASS] unknown name unchanged
  [PASS] scope validator still rejects foreign table
--- CTE + qualified refs untouched ---
  [PASS] CTE body original rewritten
  [PASS] CTE reference 's' unchanged
  [PASS] qualified ref untouched
  [PASS] qualified ref still scope-rejected
--- no schema cache -> unchanged ---
  [PASS] no schema -> original name unchanged
RESULT: ALL CHECKS PASSED
```

Frontend `npm run build` (= `vue-tsc -b && vite build`): **PASS** (only the pre-existing >500 kB chunk warning).

## Known limitations
- The AI prompt still receives physical schema names, so AI-generated SQL continues to use the long names; the rewrite makes that harmless and the manual editor now accepts the short name. (Optional follow-up: show original names in the AI prompt for consistency.)
- Alias resolution only knows tables currently in the `schema:{session_uuid}` cache; a dropped/renamed table reverts to the old behaviour (validator rejects), which is correct.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
