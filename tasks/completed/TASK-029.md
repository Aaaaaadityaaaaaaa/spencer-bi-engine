# TASK-029 — Critical Hardening: cross-tenant read on /execute (S-1) + Redis-restart data loss (S-2)

**Status: 🔲 AWAITING SIGN-OFF (2026-08-25) — all ACs proven green (3 new proof scripts + no regression); not self-closed**

## Objective
Close the two **verified 🔴 criticals** from the SaaS-readiness audit (`tasks/SAAS_READINESS.md`,
Tier 0) before Wave 6b or any real-data pilot. Both are data-safety holes an authenticated user (S-1)
or an unlucky restart (S-2) can trigger today:

- **S-1 — cross-tenant + file read via the SQL editor.** `POST /sessions/{uuid}/execute` runs any SQL
  that `sql_validator.validate()` accepts. `validate()` only proves *read-only* (single pure SELECT, no
  write nodes) — it has **no table allowlist and no function allowlist**. On Spencer's shared single-file
  DuckDB (one connection, `enable_external_access` left on because ingestion's `read_csv_auto` needs it),
  a read-only SELECT can therefore still read **another tenant's `t_<otheruuid>_*` table** or a **file**
  via `read_csv_auto('/…/uploads/…')` / `read_blob('spencer_app.db')` (the bcrypt hashes) / `read_text`.
  `run_sandboxed`'s rollback stops *writes*, not *reads*. (The transform path at `transform_service.py`
  is a **different, fail-closed** path with a function allowlist — not affected, don't conflate.)
- **S-2 — a slow Redis on restart wipes all tenant data.** Three behaviours compound: (1) `RedisManager`
  **silently** falls back to an empty in-memory `fakeredis` when real Redis is unreachable; (2) the
  cleanup sweep treats **absence of a `session:{uuid}` marker as "dead"** and drops the session's tables +
  uploads; (3) `sweep_loop` ran a sweep **immediately on boot**. So: deploy restarts → backend races up
  faster than Redis → empty fakeredis → first sweep sees zero markers → **every live session reaped**.

## Decisions / constraints that shaped the fix
- **`duckdb_manager` is frozen** and the single connection also runs ingestion, so connection-level
  `SET enable_external_access=false` is **not viable** (it would break `read_csv_auto` on upload). S-1 is
  therefore fixed at the **validator layer** with a per-session scope gate, not at the engine.
- S-1's fix is localized to **/execute only**: the AI paths (`ai_service.resolve_sql` / `_check_sql`)
  only *dry-run* SQL and never return rows, so they were never a read-exfil vector.
- `validate()` is **left unchanged** (still the shared read-only gate for all AI SQL); the new scope
  check is additive and /execute-specific.

## What it changes (all EDIT)
- **`backend/services/sql_validator.py`** — NEW `scope_violation(sql, session_uuid) -> str | None`
  (fails closed): parses (DuckDB dialect) and rejects unless every **physical** table reference starts
  with `t_<uuid>_` / `backup_<uuid>_` (CTE names defined in the statement are exempt; any
  schema/catalog-qualified name like `information_schema.*` is rejected outright), **and** there is no
  filesystem/external function anywhere (`_IO_FUNCTIONS` denylist: `read_csv*`/`read_parquet`/`read_json*`
  /`read_text`/`read_blob`/`glob`/`*_scan`/`postgres_*`/`sqlite_*`/`mysql_*`/`iceberg_*`/`delta_*` +
  `duckdb_tables`/`pragma_*` catalog enumerators), **and** no table-valued function as a FROM source
  (structural backstop: a FROM item whose body isn't a plain identifier is rejected — this catches any
  file-reading table function even if not named in the denylist). Plus a small `_function_name()` helper
  that reads a sqlglot function node's name across versions (Anonymous vs dedicated `Func`).
- **`backend/routers/ai.py`** — in `execute_query`, after `validate()`, call
  `sql_validator.scope_violation(sql, session_uuid)`; on a non-None reason raise `HTTPException(400, …)`.
- **`backend/services/redis_manager.py`** — `import config`; in the connection-failure `except`, if
  `config.IS_PRODUCTION` **raise `RuntimeError`** (clear "Redis required in production" message) *before*
  the fakeredis fallback. Dev/test still fall back (unchanged).
- **`backend/services/cleanup_service.py`** — (a) guard at the top of `sweep()`: if
  `config.IS_PRODUCTION and redis_manager.backend != "redis"`, log an error and **return without reaping**
  (defense-in-depth behind the fail-hard); (b) `sweep_loop()` now **sleeps one interval before the first
  sweep** (was immediate) so a transient startup Redis lag can't drive an instant mass-reap — first sweep
  is now `SPENCER_SWEEP_INTERVAL_MIN` (default **30 min**) after boot.

## New tests
- **`backend/test_execute_scope.py`** — 20 adversarial cases for `scope_violation` (8 allow / 12 reject):
  own-table selects, JOIN/UNION/subquery/CTE within own tables, and rich analytical funcs are **allowed**;
  another tenant's table (direct, JOIN, UNION, CTE body, subquery), `read_text`/`read_csv_auto`/`read_blob`
  /`glob`, `information_schema.tables`, `duckdb_tables()`, and a schema-qualified escape are **rejected**.
- **`backend/test_redis_failhard.py`** — (a) prod + unreachable Redis → `RuntimeError`; (b) prod +
  fakeredis backend → `sweep()` reaps 0 and the dead-looking dir is preserved; (c) dev + unreachable
  Redis → fakeredis fallback (unchanged).

## Acceptance criteria
1. ✅ **S-1 cross-tenant/file read is blocked on /execute.** *Proof:* `test_execute_scope.py`
   → `PASS: all 20 cases correct` (exit 0). Foreign-tenant tables (incl. via JOIN/UNION/CTE/subquery),
   file readers, and catalog enumerators all rejected; own-tenant analytical SQL all allowed.
2. ✅ **S-1 does not narrow legitimate queries.** Covered by the 8 MUST_ALLOW cases (GROUP BY, JOIN,
   CTE, FILTER, DATE_TRUNC, IN-subquery, `backup_*` tables) — all return `None` (allowed).
3. ✅ **S-2 fail-hard in production.** *Proof:* `test_redis_failhard.py` case (a) → `RuntimeError`
   mentioning "production"; log shows the sweep-refusal error line for case (b).
4. ✅ **S-2 sweep refuses on an untrusted store; dev unchanged.** *Proof:* `test_redis_failhard.py`
   (b) `sessions_reaped == 0` + dir preserved, (c) dev fallback `backend == "fakeredis"` →
   `PASS: all S-2 guards hold` (exit 0).
5. ✅ **No regression.** `test_sql_validator.py` → `PASS: all 25 cases correct`; all four edited modules
   import clean.
6. ✅ **Must-not-change:** `README.md`, `.ai/CURRENT_STATE.md`, and the frozen `duckdb_manager.py`
   untouched; `validate()` untouched.

## Self-review (severity-graded)
All ACs are runtime-proven in this environment (real logic, `fakeredis` for the store; no mocks of the
code under test). Findings below are the honest residuals.

**Found + fixed during this review**
- 🟠→fixed **Denylist alone would miss file-reading *table* functions.** A function-name denylist can't
  enumerate every DuckDB/extension reader (`st_read`, future readers). Added the **structural FROM check**
  (any FROM source whose body isn't a plain identifier is rejected) so *all* table-valued functions are
  blocked regardless of name — the denylist is now just the fast path + scalar-reader coverage.
- 🟢→fixed **CTE shadowing a foreign table name.** `WITH t_<other>_x AS (…) SELECT * FROM t_<other>_x`
  reads the CTE, not the base table (DuckDB resolves CTE first), so exempting CTE names is safe — but the
  CTE *body* is still scanned, so a foreign table hidden **inside** the CTE is caught. Both cases are in
  the test.

**Open findings**
- 🟠 **S-2 does not cover an *empty real Redis* (Redis data loss, not app restart).** The fix closes the
  *silent-fallback* vector (backend flips to fakeredis). If Redis itself is flushed/reset while the app
  stays connected (`backend == "redis"`, markers simply gone), the sweep guard passes and the "absent
  marker = dead" rule would still reap live data. Proper fix = an **ownership-aware sweep** that treats a
  session with a `datasets` row but no marker as *idle*, not *dead* (cross-check the identity DB), and/or
  Redis persistence (AOF). **Out of scope for TASK-029** (which targets the far more likely restart race);
  logged as a new Tier-1/2 item in `SAAS_READINESS.md` (D-2).
- 🟡 **Residual S-1 surface: an unknown *scalar* file-reader not in the denylist.** The structural check
  fully covers *table* functions; a brand-new *scalar* file-reader (used outside FROM) in a future DuckDB
  release that isn't in `_IO_FUNCTIONS` could slip. Today's scalar readers (`read_text`, `read_blob`) are
  covered. Revisit `_IO_FUNCTIONS` on DuckDB upgrades; the real belt-and-braces (engine-level external-access
  off on a dedicated read connection) is the A-1 "single-connection" follow-on's natural home.
- 🟡 **First sweep now delayed 30 min after boot.** Dead sessions from before a restart linger up to one
  extra interval before reclamation. Bounded and acceptable (storage is not tight); the manual
  `POST /admin/sweep` still runs on demand (and is itself guarded).
- 🟢 **Fail-hard raises at module import** (`redis_manager = RedisManager()`), so in prod uvicorn exits on
  boot with the RuntimeError rather than at a startup event. Intended (fail fast, clear message) and
  consistent with the module-singleton convention.
- ℹ️ **`enable_external_access` stays on** at the engine (ingestion needs it on the shared connection);
  S-1 is enforced above it at the validator. Splitting ingestion onto its own connection so the query
  path can harden the engine is the A-1 follow-on.

**Not self-closed** — left in `tasks/active/` for the single user sign-off. On sign-off: `mv` to
`tasks/completed/`, then start **Wave 6b**.

## Definition of Done
`/execute` rejects every cross-tenant and file read while still running all legitimate own-tenant
analytical SQL; production refuses to boot without real Redis and never reaps on an untrusted liveness
store; the boot-race mass-reap is removed. Proven by 3 green scripts with no regression to the existing
validator suite. The residual *empty-real-Redis* case is registered as a follow-on, not silently left.
