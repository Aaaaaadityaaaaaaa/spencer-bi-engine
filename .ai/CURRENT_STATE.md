# CURRENT_STATE.md

_Full regeneration (AP-4). Reconciled against actual code + a full green regression sweep against **real Redis** on 2026-08-21._

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
```
`test_multitable.py` prints `REDIS BACKEND IN USE: redis` when real Redis served the run, or `fakeredis` when it fell back. **If it says `fakeredis`, the Redis proof is void** (AP-9).

## Verified Implemented
- **Connection layer / AI-SQL security model — CLOSED.** Single DuckDB connection (ADR-010); `run_sandboxed()` wraps AI SQL in an unconditional-rollback transaction. Verified sequentially (TASK-001-FIX-02) and concurrently (TASK-002). Both suites now idempotent and re-runnable (AP-7).
- **Ingestion & session management (Phase 2) — VERIFIED.** `POST /sessions`, `POST /sessions/{id}/tables`, `GET /sessions/{id}/schema` (correct v1.2 multi-table array shape), plus type inference, per-column cardinality, low-cardinality sample capture, and schema-context caching.
  - Single-table, real DuckDB inference on the adversarial CSV (100 rows, 45+ cols): `ambiguous_date` → **DATE**, `mixed_col` → **VARCHAR** (card. 84), `mostly_null` → **VARCHAR** (card. 1), `category` → **VARCHAR** (card. 3, samples `["Blue","Red","Green"]`).
  - **Multi-table coexistence VERIFIED** (the long-standing blocker): `..._messy` + `..._regions` in one session, distinct names, row counts after 2nd upload `primary=100, second=6` — primary untouched, both queryable. Same-filename re-upload returns **409** instead of silently clobbering.
  - **Real-Redis proof CAPTURED** — `redis-cli GET schema:{uuid}` from an independent process returned the app-written value, a 2-table dict (2729 bytes), incl. correct BOOLEAN round-trip (`active: [false, true]`). RDB durability confirmed (`rdb_last_bgsave_status:ok`, `dump.rdb` written).
- **Data cleaning + transforms (Phase 3 — TASK-004 + TASK-005) — VERIFIED.** 10 transform ops built **Ibis compile-only** (unbound table → DuckDB SQL text, executed on `run_readwrite`; Ibis opens no connection — ADR-007): dedupe, drop_null, impute_null (zero/mean/median/**mode**/custom), cast, calculated_column, drop_column, rename_column, dedupe_subset, string_normalize, filter_rows. Per-table snapshot undo/redo/history capped at 10 (ADR-004). `calculated_column` **and** `filter_rows` share ONE fail-closed sqlglot validator with an explicit scalar-function **allowlist** — the function-allowlist residual noted in ADR-014 is CLOSED (ADR-015). Dry-run **preview** reports the row-count delta + a sample via read-only SELECTs, with no materialize/snapshot/history/version bump. Proofs: `test_transform.py` (TASK-004) and `test_transform_v2.py` (TASK-005), both green **twice** against real Redis; injection sentinel survives the predicate path; non-whitelisted funcs (`nextval`/`read_csv_auto`/`pg_sleep`) rejected in both formula and predicate.
- **SQL validator (ADR-013)** — fail-closed, 25/25 adversarial cases. This is Phase 6 defense layer 1 only; the rest of Phase 6 is unbuilt.
- **Repo is now under git** — initial commit `26639d3`, 68 files tracked, `.gitignore` verified excluding `spencer.db`, `uploads/`, `node_modules/`, `tools/`. `.env.example` added; `.env` gitignored.
- **CORS** — explicit env-driven origin allowlist (`SPENCER_CORS_ORIGINS`), default `localhost:5173`. App version bumped to `1.2.0` to match the contract.

## Not Started
- Pagination / TanStack wiring — Phase 4
- Visual canvas / charting — Phase 5
- AI layer: prompt assembly, `ai_service.generate_sql()` (still `pass`), 3-retry loop, Review Gate UI, Redis query caching — Phase 6 (validator done, nothing else)
- Scheduling / APScheduler wiring — Phase 7
- Frontend networking (Axios/Fetch) — no live calls wired yet

## Resolved This Session (2026-08-21)
| Sev | Issue | Resolution |
|---|---|---|
| MAJOR | Ingestion SQL injection + path traversal on the **non-sandboxed** path (ADR-010 never covered ingestion) | Bound parameters, identifier quote-escaping, filename sanitization (ADR-012). Sentinel-table proof: `DROP` no longer fires |
| MAJOR | `sql_validator.validate()` returned `True` unconditionally — fail-open | Reimplemented fail-closed with sqlglot (ADR-013), 25/25 adversarial |
| MAJOR | `redis_manager` could never reach real Redis (hardcoded fakeredis, ignored host/port) | Real client + explicit logged fallback + `.backend` (ADR-011) |
| MAJOR | `main.py` called removed `get_readonly_connection()` → `AttributeError` | Repointed to `get_readwrite_connection()` |
| MAJOR | Both security proof suites could only pass **once** (no teardown vs persistent `spencer.db`); failure impersonated a security regression | Made idempotent, shown green twice consecutively (AP-7) |
| MAJOR | Docs contradicted code on the security-critical path (`CURRENT_STATE` claimed the disproven dual-connection design was implemented; ADR-010 status stale; ingestion listed "Not Started" while implemented) | Reconciled; ADR-008 superseded, ADR-011/012/013 + AP-7/8/9 added |
| MINOR | CORS `allow_origins=["*"]` + `allow_credentials=True` (invalid combo browsers reject) | Env-driven explicit allowlist |
| MINOR | `fakeredis` imported but never declared — fresh install would fail at import | Declared under `[project.optional-dependencies] dev` |
| MINOR | `set_json` would crash on DuckDB DATE/Decimal sample values | `json.dumps(..., default=str)` |
| MINOR | App version `1.1.0` lagged the v1.2 contract | Bumped to `1.2.0` |

## Known Gaps (open)
- **Redis is a manually-started portable binary, not a service** — does not survive reboot. Must be resolved before Phase 7 (APScheduler persistence) is trusted operationally. See ADR-011 amendment.
- **Schema cache keys have no TTL** (`redis-cli TTL` → `-1`) — concrete instance of the session-cleanup gap below.
- No session/data cleanup mechanism — `backend/uploads/` already holds orphaned session dirs and `spencer.db` accumulates test tables from every run.
- APScheduler job store not yet persistent (Redis-backed) — scheduled jobs would vanish on restart.
- No LLM API cost/rate control.
- No file upload **size** cap or MIME/extension allowlist (filename is now sanitized, but nothing bounds size).
- No row cap on ad-hoc `/execute` results.
- `GET /health` is liveness-only — does not verify Redis/DuckDB reachability (and so would not have surfaced the fakeredis substitution).
- No central FastAPI exception handler yet (CODING_STANDARDS requires uniform error shape).
- `ai_service.generate_sql()` is still `pass` — must not be wired until Phase 6 is a real task.
- Portable Redis is **5.0.14.1**; production Redis 6/7 supports RESP3. `protocol=2` is pinned for compatibility — revisit if the server is upgraded.

## Next Recommended Task
**Phase 4 — Virtualized data grid + pagination + first real frontend↔backend wiring.** Backend: a paginated read endpoint (offset/limit or keyset) over a session's live table. Frontend: a TanStack Table virtualized grid wired to that endpoint via Axios — the first live network call (the frontend is a component shell today). Closes the "no live calls wired yet" gap.
Pre-req reminder: start real Redis first, and require `REDIS BACKEND IN USE: redis` in any proof that touches the cache.
