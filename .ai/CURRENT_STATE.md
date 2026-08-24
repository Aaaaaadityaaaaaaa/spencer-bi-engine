# CURRENT_STATE.md

_Full regeneration (AP-4). Reconciled against actual code. TASK-001…011 verified against **real Redis** (2026-08-21 / 2026-08-22). TASK-013 (deployability hardening) verified against real Redis on 2026-08-22 and **awaiting user sign-off** (not self-closed)._

## How To Reproduce The Current Green State
Real Redis must be running first (it is NOT a service — it does not survive a reboot, see ADR-011 amendment):
```
cd "E:/SPENCER V1/tools/redis" && ./redis-server.exe --port 6379 --save 60 1
```
Then, from `backend/`:
```
python test_transaction_rollback_full.py   # 4/4  rollback sandbox (ADR-010)
python test_concurrent.py                  # 2/2  concurrency (TASK-002)
python test_multitable.py                  # 4/4  multi-table + injection (TASK-003)
python test_sql_validator.py               # 25/25 adversarial SQL validation (ADR-013)
python test_ingestion.py                   # single-table ingestion
python test_transform.py                   # 5 cleaning ops + snapshot undo/redo (TASK-004)
python test_transform_v2.py                # +5 ops, predicate filter, function allowlist, dry-run preview (TASK-005)
python test_data_endpoint.py               # 22/22 paginated /data + virtualized-grid backend (TASK-006)
python test_cleanup.py                      # 13/13 cleanup sweep + TTL + cap layers (TASK-013)
```
Any cache-touching proof prints `REDIS BACKEND IN USE: redis` when real Redis served the run, or `fakeredis` when it fell back. **If it says `fakeredis`, the Redis proof is void** (AP-9). `test_cleanup.py` requires `spencer.db` to be openable, so **stop the uvicorn backend before running it** (DuckDB is single-writer, single-file).

## Verified Implemented
- **Connection layer / AI-SQL security model — CLOSED.** Single DuckDB connection (ADR-010); `run_sandboxed()` wraps AI SQL in an unconditional-rollback transaction. Verified sequentially (TASK-001-FIX-02) and concurrently (TASK-002). Both suites now idempotent and re-runnable (AP-7).
- **Ingestion & session management (Phase 2) — VERIFIED.** `POST /sessions`, `POST /sessions/{id}/tables`, `GET /sessions/{id}/schema` (correct v1.2 multi-table array shape), plus type inference, per-column cardinality, low-cardinality sample capture, and schema-context caching.
  - Single-table, real DuckDB inference on the adversarial CSV (100 rows, 45+ cols): `ambiguous_date` → **DATE**, `mixed_col` → **VARCHAR** (card. 84), `mostly_null` → **VARCHAR** (card. 1), `category` → **VARCHAR** (card. 3, samples `["Blue","Red","Green"]`).
  - **Multi-table coexistence VERIFIED**: `..._messy` + `..._regions` in one session, distinct names, row counts after 2nd upload `primary=100, second=6` — primary untouched, both queryable. Same-filename re-upload returns **409** instead of silently clobbering.
  - **Real-Redis proof CAPTURED** — `redis-cli GET schema:{uuid}` from an independent process returned the app-written value, a 2-table dict (2729 bytes), incl. correct BOOLEAN round-trip (`active: [false, true]`). RDB durability confirmed (`rdb_last_bgsave_status:ok`, `dump.rdb` written).
- **Data cleaning + transforms (Phase 3 — TASK-004 + TASK-005) — VERIFIED.** 10 transform ops built **Ibis compile-only** (unbound table → DuckDB SQL text, executed on `run_readwrite`; Ibis opens no connection — ADR-007): dedupe, drop_null, impute_null (zero/mean/median/**mode**/custom), cast, calculated_column, drop_column, rename_column, dedupe_subset, string_normalize, filter_rows. Per-table snapshot undo/redo/history capped at 10 (ADR-004). `calculated_column` **and** `filter_rows` share ONE fail-closed sqlglot validator with an explicit scalar-function **allowlist** (ADR-015). Dry-run **preview** reports the row-count delta + a sample via read-only SELECTs, with no materialize/snapshot/history/version bump. Proofs: `test_transform.py` + `test_transform_v2.py`, both green **twice** against real Redis; injection sentinel survives the predicate path; non-whitelisted funcs (`nextval`/`read_csv_auto`/`pg_sleep`) rejected in both formula and predicate.
- **Virtualized data grid + pagination + first live frontend↔backend wiring (Phase 4 — TASK-006) — VERIFIED.** `GET /sessions/{id}/data?offset&limit&table_name` returns `{columns:[{name,type}], rows, total, offset, limit}` over a session's live table on the **read-write path** (`run_readwrite`; `run_sandboxed` / `duckdb_manager.py` untouched). `ORDER BY rowid` gives stable, disjoint, complete infinite-scroll windows; `limit` clamped `[1,1000]`, `offset` `[0,…]`, ints only; `table_name` resolved via `_resolve_table` (unknown → 404) and `_quote_ident`-quoted — no user string reaches SQL (AP-8). Frontend makes **real Axios calls**; `DataGrid` (`@tanstack/vue-virtual`) fetches 500-row windows and appends on scroll with a `rows.length >= total` stop guard. Proof `test_data_endpoint.py` — 22 checks green **twice** against real Redis; strict `vue-tsc` build clean.
- **Canvas dashboard aggregation + KPI/chart tiles (Phase 5 — TASK-011) — VERIFIED (signed off 2026-08-22).** `POST /sessions/{id}/aggregate` serves scalar KPIs and grouped top-N series, built **Ibis compile-only** with a fresh per-request schema, fail-closed validation (unknown column / non-numeric measure / bad aggregation → 400), `_resolve_table` single-table (ADR-006), server-clamped top-N `limit` `[1,200]`. Frontend Canvas auto-seeds a KPI-card row + a configurable chart tile from the live schema, computes every number **server-side over the full table**, refreshes via one `dataVersion` watch. Hand-built **modular** ECharts (ADR-005). Proof: 18 curl cases + live browser verification; strict `vue-tsc -b && vite build` clean. **No committed pytest suite for this endpoint yet** — a `test_aggregate.py` is a sensible follow-up.
- **Deployability hardening: upload cap + session TTL + cleanup sweep (TASK-013) — VERIFIED 2026-08-22, AWAITING SIGN-OFF.** Single-VM / disposable posture (decisions locked with the user). Three coordinated pieces, all via allowed surfaces (`duckdb_manager.py` frozen; every DROP/CHECKPOINT/PRAGMA/`information_schema` read routes through `run_readwrite`):
  - **Upload guardrails** — a `SPENCER_MAX_UPLOAD_MB` (default 100) cap enforced in three layers: an nginx `client_max_body_size` in front (documented ops step, the true pre-server gate), a Content-Length middleware early-reject (**413**), and a streaming byte-count backstop in `_persist_upload` that removes the partial file and raises **413** on chunked/absent/lying Content-Length. Plus a `SPENCER_UPLOAD_ALLOWED_EXT` (default `csv`) extension allowlist → **415** before any bytes persist (fails closed on no-extension).
  - **Session liveness + sliding TTL** — a `session:{uuid}` marker (TTL `SPENCER_SESSION_TTL_HOURS`, default 24h) *defines* the session lifetime. `touch_session` (SET+EXPIRE) on create/upload before persisting (anti-race: marker before dir); `refresh_session` (EXPIRE-only, no resurrection) slid by a `/sessions/{uuid}/...` request middleware so an actively-used session — including read-only queries — never ages out.
  - **Cleanup sweep** (`cleanup_service.sweep`) — reclaims each dead session's DuckDB tables + `uploads/{uuid}/` dir + Redis keys; idempotent; skips dirs within a `SPENCER_SWEEP_GRACE_MIN` (default 15) window; `CHECKPOINT` once after drops. **AP-8:** the filesystem-derived uuid is NEVER interpolated into SQL — the catalog is snapshotted, names filtered in Python by identifier prefix, and only catalog-sourced quote-escaped identifiers are dropped. Runs on startup and every `SPENCER_SWEEP_INTERVAL_MIN` (default 30) via a bare-asyncio task (independent of the unbuilt Phase-7 job store), cancelled on shutdown. Manual `POST /admin/sweep`; metrics `GET /admin/storage`.
  - **DuckDB startup hardening** — `PRAGMA memory_limit` (default 4GB, operator value regex-validated) + optional `temp_directory` applied at startup via `run_readwrite`, closing the documented-but-unimplemented `memory_limit` claim.
  - **Proof (real Redis, AP-9):** `test_cleanup.py` 13/13 green **twice** (DEAD reaped; LIVE + within-grace GRACE preserved; re-sweep stable). Its first live run reclaimed **63 real orphaned session dirs / 56 tables / ~48 MB** of pre-existing cruft. Live HTTP: `.json`/`.txt` → 415; 2.9 MB upload vs 1 MB cap → 413 (middleware) with no dir/table created; small CSV → 200; streaming backstop → 413 + partial removed (standalone, Content-Length bypassed); `/admin/storage` shows `duckdb_memory_limit:"3.7 GiB"` (startup PRAGMA effective), `live_sessions`, `orphan_dirs`; marker TTL slides on activity (86348→86400 after a GET); bogus uuid → 404 with no marker created; `/admin/sweep` leaves the live session untouched.
- **SQL validator (ADR-013)** — fail-closed, 25/25 adversarial cases. Phase 6 defense layer 1 only; the rest of Phase 6 is unbuilt.
- **Repo under git** — `.gitignore` excludes `spencer.db`, `uploads/`, `node_modules/`, `tools/`; `.env` gitignored, `.env.example` tracked.
- **CORS** — explicit env-driven origin allowlist (`SPENCER_CORS_ORIGINS`), default `localhost:5173`. Registered so `CORSMiddleware` stays outermost (wraps the TASK-013 deploy-guard middleware, so an early 413 still carries CORS headers). App version `1.2.0`.

## Not Started
- AI layer: prompt assembly, `ai_service.generate_sql()` (still `pass`), 3-retry loop, Review Gate UI, Redis query caching — Phase 6 (validator done, nothing else).
- Scheduling / APScheduler wiring — Phase 7.
- `DELETE /sessions/{uuid}` is still a stub returning `{"status":"deleted"}` — cleanup now exists in `cleanup_service`, so wiring DELETE to a shared reclaim path is a small follow-up (out of TASK-013's approved scope; not done, AP-2).

## Resolved This Session (2026-08-22 — TASK-013)
| Sev | Gap (was open) | Resolution |
|---|---|---|
| MAJOR | No session/data cleanup — `uploads/` + `spencer.db` grew forever | `session:{uuid}` sliding-TTL marker + idempotent periodic sweep (tables + dir + Redis keys); reclaimed 63 orphans / ~48 MB on first live run |
| MAJOR | No upload size cap or MIME/extension allowlist | 3-layer size cap (proxy / Content-Length 413 / streaming backstop 413) + extension allowlist (415), verified live |
| MINOR | `PRAGMA memory_limit` documented as enforced but never applied | Applied at startup via `run_readwrite` (frozen manager untouched); confirmed `3.7 GiB` via `/admin/storage` |
| MINOR | Session/schema keys had no lifetime | Sliding TTL defines session lifetime; dead-session keys purged by the sweep |
| MINOR | `/health` liveness-only, no storage visibility | `GET /admin/storage` (disk/uploads/db bytes, table count, live sessions, orphan dirs, memory_limit) |

## Known Gaps (open)
- **Redis is a manually-started portable binary (5.0.14.1), not a service** — does not survive reboot. Disposable-data consequence (intended, documented): on a Redis wipe all liveness markers vanish and the next sweep reclaims every `uploads/` dir + its tables — a fresh start, not a bug. Must still be resolved before Phase 7 (APScheduler persistence) is trusted operationally. `protocol=2` pinned for RESP2 compat; revisit if the server is upgraded to 6/7.
- **Orphan DuckDB tables with no `uploads/` dir are not reclaimed by the sweep** (the sweep is dir-indexed). In production every table is created through ingestion, which always creates a dir + marker, so this does not leak in normal operation — but test scripts that `CREATE TABLE` directly (and the `table_count:8` seen during verification) do leave such tables. Follow-up: a catalog-driven pass that reverse-maps `t_{uuid}_`/`backup_{uuid}_` names to a uuid and drops any owned by neither a live marker nor a dir (Low severity — dev-only artifact, and it widens the DROP surface, so it wants explicit sign-off).
- **nginx `client_max_body_size` is a required deploy step, not code** — it is the only truly pre-server upload gate; the app layers are defense-in-depth. Set it to match `SPENCER_MAX_UPLOAD_MB`.
- No LLM API cost/rate control (`SPENCER_MAX_LLM_CALLS_PER_SESSION` still a commented Phase-8 knob).
- No row cap on ad-hoc `/execute` results once the AI layer is built (`MAX_ROWS` constant exists; endpoint unbuilt).
- No central FastAPI exception handler yet (CODING_STANDARDS requires uniform error shape). The new 413/415 use `HTTPException` consistent with existing 404/409.
- `ai_service.generate_sql()` is still `pass` — must not be wired until Phase 6 is a real task.

## Next Recommended Task
**Query Engine (Phase 6 — AI NL→SQL layer behind a MySQL-Workbench-style SQL editor)** — the last product
pillar still in its original "Ask AI" state, and the standing product-vision priority. Wire
`ai_service.generate_sql()` (still `pass`) through the already-green fail-closed `sql_validator` (ADR-013) →
`run_sandboxed` (unconditional-rollback) → a **Review Gate** UI that shows the generated SQL before it runs,
with Redis query caching; front it with a SQL editor + results grid, keeping the AI-assist path.
_(Note: TASK-012 "Query Engine ergonomics" is in flight in a separate session and awaiting sign-off; reconcile with it before starting.)_
Deploy follow-ups from TASK-013: document the nginx `client_max_body_size` step and consider the orphan-table
reclamation pass above. Pre-req reminder: start real Redis first, and require `REDIS BACKEND IN USE: redis`
in any proof that touches the cache.
