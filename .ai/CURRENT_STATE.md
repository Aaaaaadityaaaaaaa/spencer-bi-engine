# CURRENT_STATE.md

_Last reconciled against actual code + a real test run on 2026-08-21._

## Implemented (verified)
- Repo scaffolding: FastAPI + routers + services (`duckdb_manager.py`, `redis_manager.py`, `ai_service.py`, `sql_validator.py`) + Vue 3/TS/Tailwind/TanStack/ECharts frontend shell
- `docker-compose.yml` (Redis service defined — NOT runnable in current dev env, see Known Gaps)
- `pyproject.toml` (uv-intended; `uv` unavailable in dev environment — pip-compatible fallback in use)
- `GET /health` endpoint (liveness only — does not verify Redis/DuckDB reachability)
- `duckdb_manager.py`: `ThreadPoolExecutor`/`run_in_executor` wrapper; **single `duckdb.connect()` per ADR-010.** `run_readwrite()` and `run_sandboxed()` (unconditional-rollback transaction) implemented and verified — sequential (TASK-001-FIX-02) and concurrent (TASK-002).

## Resolved
- ADR-003's dual read-write/read-only connection design was tested and disproven; reported via `ARCHITECTURAL_CHANGE_REQUEST`. **Superseded by ADR-010.** (Correction 2026-08-21: the prior version of this file still listed the disproven dual-connection design as "implemented" under line 8 — that was doc drift; the code has only ever shipped the single-connection model.)
- ADR-010 (single-connection transaction-rollback) implemented and verified sequentially + concurrently. AI-query security model closed.

## Implemented But NOT Yet Verified (do NOT treat as done)
- **AI layer, cleaning, charting, scheduling remain genuinely unbuilt** — see Not Started below.

## Ingestion — VERIFIED 2026-08-21 (except real-Redis leg)
`routers/session.py` was already substantially implemented (NOT stubbed, contrary to the prior version of this file). Verification run + fixes completed under TASK-003:
- **Single-table upload VERIFIED** with real output against `backend/messy.csv` (100 rows, 45+ cols): `ambiguous_date` → DATE, `mixed_col` → VARCHAR (card. 84), `mostly_null` → VARCHAR (card. 1), `category` → VARCHAR (card. 3).
- **Multi-table coexistence VERIFIED** (was the standing blocker): `..._messy` + `..._regions` in one session, distinct names, row counts after 2nd upload `primary=100, second=6` — primary untouched, both queryable. Same-filename re-upload now returns **409** instead of silently clobbering.
- **`GET /schema` VERIFIED** returning the v1.2 multi-table array with correct `is_primary` flags. (It was already correct — the "stubbed against old v1.1 shape" claim was itself stale; `models/schemas.py` needed no change.)
- **Schema-cache round-trip VERIFIED** — correctly keyed by both table names — **but served by `fakeredis`, not real Redis.** Criterion #3 remains OPEN.

## Currently Blocked
- **TASK-003 criterion #3 only** (real Redis value via `redis-cli GET`). Decision made: **Memurai** (ADR-011). `redis_manager.py` is now wired for a real client with explicit logged fallback, so this closes as soon as Memurai is installed — re-run `test_multitable.py` and confirm it prints `REDIS BACKEND IN USE: redis`. Nothing else is blocked.

## Not Started
- Cleaning/undo-redo implementation (endpoints stubbed only)
- Pagination / TanStack wiring
- Visual canvas / charting
- AI layer (prompt assembly, sqlglot validation, retry loop, Redis caching)
- Scheduling (APScheduler wiring — job store persistence not yet configured)
- Frontend networking (Axios/Fetch) — no live calls wired yet

## Known Gaps
- **[RESOLVED 2026-08-21] `redis_manager.py` real-Redis client** — rewritten per ADR-011 (real `redis.Redis` + logged fakeredis fallback + inspectable `.backend`). Real-Redis *proof* still pending Memurai.
- **[RESOLVED 2026-08-21] `main.py` `get_readonly_connection()` AttributeError** — repointed to `get_readwrite_connection()`.
- **[RESOLVED 2026-08-21] Ingestion SQL injection / path traversal** — fixed via bound parameters + identifier escaping + filename sanitization; proven with a sentinel-table test (ADR-012).
- **[RESOLVED 2026-08-21] Security proof suites were non-repeatable** — `test_transaction_rollback_full.py` / `test_concurrent.py` created `probe_table` with no teardown against the persistent `spencer.db`, so they could only pass once and then failed with a `CatalogException` that *impersonates a security regression*. Made idempotent and demonstrated green across two consecutive runs (12/12 assertions). See CODING_STANDARDS.md AP-7.
- [MINOR] CORS IS configured in `main.py` as `allow_origins=["*"]` + `allow_credentials=True` (invalid browser combo). Prior note "No CORS yet" was wrong. Needs a real origin allowlist before frontend networking.
- [MINOR] FastAPI app `version="1.1.0"` lags the v1.2 contract.
- No session/data cleanup mechanism (uploads, DuckDB tables, Redis keys accumulate indefinitely). Note: `backend/uploads/` already holds orphaned session dirs from test runs, and `spencer.db` accumulates test tables — visible evidence of this gap.
- APScheduler job store not yet persistent (Redis-backed) — scheduled jobs would vanish on restart.
- No LLM API cost/rate control.
- No file upload size/type validation (size cap, MIME/extension allowlist) — filename is now sanitized, but nothing bounds upload size.
- No row cap on ad-hoc `/execute` results.
- Secrets management (`.env` + `.gitignore`) not yet confirmed in place.
- This project directory is **not a git repository** yet — the "versioned docs in the repo" are not actually under version control.

## Next Recommended Task
1. **Install Memurai** → close TASK-003 criterion #3 (only remaining item on TASK-003).
2. **TASK-004 — Data Cleaning ("Drop & Scrub")** per Phase 3: dedupe, missing-value handling, type change, calculated columns, per-table undo/redo (ADR-004 snapshots, capped 5–10), all built via Ibis (ADR-007). Note Ibis is **not yet a dependency** — adding it is part of that task.

