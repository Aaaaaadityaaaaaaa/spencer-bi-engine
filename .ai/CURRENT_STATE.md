# CURRENT_STATE.md

_Reconciled against actual code on **2026-08-29** (Phase 0 doc-sync, TASK-042). The prior version
(2026-08-22, TASK-013) pre-dates Authentication/multi-tenancy (TASK-027), SaaS hardening (TASK-029),
the Phase 6/7 Query Engine + Scheduling build-out, and feature Waves 1–7. This rewrite replaces it._

> **Verification note.** Items carried from the 2026-08-22 doc were proven against real Redis at that
> time (see "How to reproduce"). The post-TASK-027 additions (auth, multi-tenancy, AI Query Engine,
> Scheduling, Waves) are **code-verified** from the source + their dedicated test suites
> (`test_auth.py`, `test_tenant_isolation.py`, `test_execute_scope.py`, `test_ai_wave4.py`,
> `test_aggregate_2d.py`) but were **not re-run live in this reconciliation session**. Re-run the
> battery (below) before claiming a green state for sign-off.

## How To Reproduce A Green State
Real Redis must be running first (it is NOT a service — it does not survive a reboot, ADR-011):
```
cd "E:/SPENCER V1/tools/redis" && ./redis-server.exe --port 6379 --save 60 1
```
From `backend/`, the suites that exist today:
```
python test_transaction_rollback_full.py   # rollback sandbox (ADR-010)
python test_multitable.py                  # multi-table + injection (TASK-003)
python test_sql_validator.py               # 25/25 adversarial SQL validation (ADR-013)
python test_transform.py                   # cleaning ops + snapshot undo/redo
python test_transform_v2.py                # + ops, predicate filter, function allowlist, preview
python test_data_endpoint.py               # paginated /data + virtualized-grid backend
python test_auth.py                        # registration / login / token / logout
python test_tenant_isolation.py            # cross-tenant table isolation (TASK-027)
python test_execute_scope.py               # /execute tenant-scoping + filesystem-block (TASK-029 S-1)
python test_ai_wave4.py                    # Wave 4 AI endpoints (assist/suggest/narrate/recommend/explain)
python test_aggregate_2d.py                # 2-D breakdown aggregation (Wave 5)
python test_cleanup.py                     # cleanup sweep + TTL + cap layers (TASK-013)
```
Any cache-touching proof prints `REDIS BACKEND IN USE: redis` when real Redis served the run, or
`fakeredis` when it fell back — **if it says `fakeredis`, the Redis proof is void.** `test_cleanup.py`
requires `spencer.db` to be openable, so **stop the uvicorn backend before running it** (DuckDB is
single-writer, single-file).

## Verified Implemented (carried from 2026-08-22, real-Redis proven)
- **Connection layer / AI-SQL security model — CLOSED.** Single DuckDB connection (ADR-010);
  `run_sandboxed()` wraps AI SQL in an unconditional-rollback transaction.
- **Ingestion & session management (Phase 2).** `POST /sessions`, `POST /sessions/{id}/tables`,
  `GET /sessions/{id}/schema` (multi-table array), type inference, per-column cardinality, low-
  cardinality sample capture, schema-context caching. Multi-table coexistence + 409 on name clash.
- **Data cleaning + transforms (Phase 3).** 10+ ops built Ibis compile-only (ADR-007): dedupe,
  drop_null, impute_null, cast (+coerce), calculated_column, drop_column, rename_column, dedupe_subset,
  string_normalize, filter_rows, **split_column, date_extract, bin_column, fill_down, flag_outliers,
  absolute_value** (Wave 1 ops, all present in `transform_service.py`). Per-table snapshot undo/redo
  capped at 10 (ADR-004). `calculated_column` + `filter_rows` share ONE fail-closed sqlglot validator
  with an explicit scalar-function **allowlist** (ADR-015). Dry-run **preview** (no materialize).
- **Virtualized data grid + pagination (Phase 4).** `GET /sessions/{id}/data` windowed; `DataGrid`
  (`@tanstack/vue-virtual`) 500-row windows; `ORDER BY rowid` stable disjoint windows.
- **Canvas aggregation + tiles (Phase 5).** `POST /sessions/{id}/aggregate` scalar KPIs + grouped
  top-N series; 2-D breakdown (series dimension) supported. KPI cards + chart tiles auto-seeded.
- **Deployability hardening (TASK-013).** 3-layer upload cap (413) + extension allowlist (415);
  sliding-TTL session marker + periodic sweep reclaiming tables/dirs/Redis keys; `PRAGMA memory_limit`
  at startup; `GET /admin/storage`; `POST /admin/sweep`; `POST /admin/kill-query`.
- **SQL validator (ADR-013).** Fail-closed, 25/25 adversarial cases.
- **`DELETE /sessions/{uuid}`** — now fully wired (TASK-013 follow-up, AP-2): drops DuckDB tables,
  purges Redis keys + upload dir, deletes the ownership row. (Prior doc incorrectly called it a stub.)
- **Scheduling (Phase 7).** `routers/schedule.py`: `POST/GET /schedules`, `DELETE /schedules/{id}`,
  `GET /schedules/{id}/runs`. In-process scheduler thread; Redis-backed persistence for run state.

## Built since 2026-08-22 (code-verified; re-run suites for sign-off)
- **Authentication & multi-tenancy (TASK-027).** `POST /auth/register|login`, `GET /auth/me`,
  `POST /auth/logout`; JWT bearer auth via `get_current_user`; `ownership_service` maps
  session→user→tables in `app_db` (SQLAlchemy). `require_session_owner` dependency 404s any request
  for a session the caller does not own. Frontend `useAuth` + `AuthView` (Login/Register) + App shell
  gated behind auth. `deps.py` wires `get_db` (app_db session) + `get_current_user`.
- **SaaS hardening — tenant scoping (TASK-029 S-1/S-2).** `/execute` and `/materialize` now enforce
  `sql_validator.scope_violation()`: a query may only touch THIS session's own `t_{uuid}_*` tables and
  may not call filesystem/external functions (`read_csv_auto`/`read_parquet`/etc.) — closing the
  cross-tenant read + file-exfil paths on the shared single-file DuckDB. (S-3 per-user quota and S-4
  rate limiting remain open — see Gaps.)
- **Query Engine (Phase 6) — NL→SQL + execution + AI assists, fully wired.** `ai.py`:
  `/ask` (NL→validated SELECT, version-keyed cache, bounded self-correction), `/execute` (Review Gate;
  validated + sandboxed), `/sql/assist` (explain/fix/optimize), `/suggest-questions` (#26 auto-EDA),
  `/narrate` (#29 storytelling), `/recommend-chart` (#30), `/explain-chart` (#18). Frontend:
  `QueryConsole` (generate/run/explain/optimize/fix/materialize), `SuggestedQuestions`,
  `CustomInstructions`. `ai_service` uses LiteLLM with a key pool (`llm_key_pool`). `/materialize`
  persists a reviewed SELECT as a new table (ADR-006 switcher).
- **Multi-table switcher UI (#32 / TASK-039).** `TableSwitcher.vue` + `App.vue` mount: lists session
  tables, switches the active table across all tabs, "Add table" uploads a secondary.
- **Round-trip export (Wave 2 / #10, #24).** Backend `/export` (table: csv/tsv/json/parquet/xlsx) +
  `/export/rows` (xlsx). Frontend `ExportMenu.vue` (table → all formats) + `QueryConsole` "Export .xlsx"
  (result rows).
- **Column profiler (#1 / TASK-015) + Data-quality panel (#2 / TASK-016).** `profile_service`,
  `quality_service`; `ColumnProfilePanel`, `DataQualityPanel` with one-click Fix.
- **In-grid: inline edit (#5 / TASK-041) + heatmap (#22).** `update_cell` op; whole-table numeric
  ranges drive grid heatmap. Multi-sort / pin / freeze NOT yet built (Wave 3 open).
- **Canvas chart types.** Rendered: bar, line, area, hbar, **stacked**, **heatmap**, pie. NOT yet
  rendered: scatter, box, treemap, funnel (Wave 5 open — the `ChartType` union admits them but
  `ChartTile` has no render branch).

## Not Started / Genuinely Missing
- **Wave 3 in-grid power:** multi-column sort, column pin/freeze, drag-reorder (search + hide/show +
  inline-edit + heatmap already exist).
- **Wave 5 chart types:** scatter, box, treemap, funnel rendering branches in `ChartTile.vue` (need a
  2-D aggregate contract already present for scatter/box).
- **Wave 6 dashboard persistence:** live auto-persist exists (`useActiveDashboard`, localStorage);
  **named Save/Load + templates are NOT built** (`useDashboards` slot reserved, TASK-035).
- **Wave 7:** parameterized queries (`:param`/`{{var}}` handling), session I/O (export/import a session
  as a file). Result→Canvas tile IS built (materialize + seedChartOnCanvas).
- **Phase 0 doc sync (this task):** `.ai/ARCHITECTURE.md` and `.ai/DECISIONS.md` still describe the
  pre-auth single-user app and are stale; they need the same reconciliation as this file.

## Known Gaps / Open (architectural — need a decision before touching DB/auth)
- **S-3 per-user LLM quota / attribution** — thread `user_id` into `ai_service._call_llm`; no cost cap.
- **S-4 rate limiting** — missing on `/auth/*` and AI endpoints.
- **D-1 Redis→app_db catalog mirror** — `schema:{uuid}` lives only in Redis; a Redis flush loses the
  catalog (tables survive in DuckDB, but the app can't see them). Mirror into `app_db`.
- **D-2 ownership-aware sweep** — `cleanup_service` is dir/indexed; should never reap owned sessions and
  should cover orphan tables.
- **I-1 Alembic migrations** — `app_db` schema is created imperatively; no versioned migrations.
- **I-2 backups** — no `pg_dump`/DuckDB snapshot strategy.
- **P-1 billing, P-2 password reset, P-3 observability** — not built.
- **P-4 hide Register tab** — AuthView has a Login/Register toggle; hiding Register (invite-only) is a
  product decision, not yet implemented.
- Redis is a manually-started portable binary (5.0.14.1), not a service — does not survive reboot
  (disposable-data consequence; must be resolved before Scheduling is operationally trusted).
- No central FastAPI exception handler yet (CODING_STANDARDS wants a uniform error shape).
- Orphan DuckDB tables with no `uploads/` dir are not reclaimed by the dir-indexed sweep (Low; dev-only).

## Next Recommended Task
Reconcile `ARCHITECTURE.md` + `DECISIONS.md` (carry the auth/multi-tenancy + SaaS-hardening narrative),
then execute the genuinely-missing feature waves (Wave 3 → 5 → 6 → 7) and raise an
`ARCHITECTURAL_CHANGE_REQUEST` per item before any DB/auth change above.
