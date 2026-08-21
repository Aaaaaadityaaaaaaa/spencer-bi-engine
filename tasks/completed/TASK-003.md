# TASK-003

## Title
Ingestion & Session Management

## Objective
Implement multi-file upload, session creation, DuckDB type inference/table registration, and schema context caching to Redis, per REQUIREMENTS.md and API.md.

## Context
First real feature work since the connection-layer fixes (TASK-001-FIX-02, TASK-002). This does not touch `run_sandboxed()` at all — it only uses `run_readwrite()`.

## Requirements
1. `POST /sessions` — first upload, generates `session_uuid`, registers as primary table
2. `POST /sessions/{session_uuid}/tables` — additional file upload into an existing session, registers as a new (non-primary) table
3. `GET /sessions/{session_uuid}/tables` — list tables in session
4. DuckDB native sniffing for type inference on every upload
5. Table naming: `t_{session_uuid}_{tablename}` (DATABASE.md)
6. Schema context computation (DDL + per-column cardinality + sample values for low-cardinality columns) cached to Redis under `schema:{session_uuid}` — **multi-table dict shape**, per DATABASE.md: `{table_name: {ddl, cardinality, samples}}`
7. `GET /sessions/{session_uuid}/schema` — **must return the v1.2 multi-table array shape, not the old v1.1 single-table shape.** This was already stubbed against the old shape in Day 2 scaffolding — this is a required correction, not new work only.

## Existing Components
`backend/routers/session.py` (stubs exist), `backend/services/duckdb_manager.py` (`run_readwrite()` — do not touch `run_sandboxed()` or its tests), `backend/services/redis_manager.py` (stub).

## Files Expected To Change
`backend/routers/session.py`, `backend/services/redis_manager.py`, `backend/models/schemas.py` (update `GET /schema` response model to the multi-table shape).

## Files That Must NOT Change
`duckdb_manager.py`'s connection/transaction logic (TASK-001-FIX-02/TASK-002 territory — closed, do not reopen without a review-driven reason).

## Technical Constraints
Use the messy test CSV requirements from the original roadmap: mixed-type column, ambiguous date column, >90% null column, low-cardinality categorical column, 45+ total columns (to exercise schema-context computation at the scale the future pre-filter mitigation assumes, even though the pre-filter itself isn't built yet).

## Dependencies
TASK-001-FIX-02, TASK-002 (both completed).

## Implementation Guidance
Follow API.md for exact request/response shapes. Follow DATABASE.md for the Redis key shape. Do not invent additional fields not in the contract — if something's ambiguous, flag `BLOCKED_ON_DECISION` rather than guessing.

## Acceptance Criteria
- Real response JSON from `POST /sessions` against the messy test CSV, including what DuckDB actually inferred for the ambiguous/mixed-type columns
- Real response JSON from `GET /sessions/{session_uuid}/schema` — must show the multi-table array shape
- Real Redis value from `schema:{session_uuid}` (e.g. via `redis-cli GET`), not a description of its shape
- Confirm the low-cardinality column's captured sample values are correct — paste them

## Tests Required
Upload the messy CSV, call each new/changed endpoint, paste all four proofs above.

## Edge Cases
- What does DuckDB actually guess for the ambiguous date column (e.g. `03/04/2025`)? Report it plainly — this is useful information regardless of whether it's "right."
- Confirm a second file upload into the same session doesn't collide with or overwrite the primary table.

## Security Considerations
None specific to this task — no AI/execution path involved.

## Performance Considerations
None specific — full load-testing at scale is a later phase (per ROADMAP), not required here.

## Definition Of Done
All four proofs in Acceptance Criteria present as real output; `GET /schema` returns the corrected v1.2 shape.

## Status
**COMPLETED — signed off 2026-08-21 (closed by commit c28573c).** All 4 acceptance criteria MET with real output against real Redis; full regression sweep green (rollback 4/4, concurrency 2/2, multi-table+injection 4/4, SQL validator 25/25, ingestion green).
Originally Re-scoped 2026-08-21 from "implement" to "verify + fix": the ingestion code already existed (contrary to CURRENT_STATE.md, which listed it as Not Started). 3 of 4 acceptance criteria met with real output; criterion #3 (real Redis) formally OPEN pending Memurai (ADR-011).

## Proofs Captured 2026-08-21 (real output, run via `python test_multitable.py`)

### Criterion 1 — POST /sessions against the messy CSV (PASS)
Real DuckDB inference on the adversarial columns:
- `ambiguous_date` -> **DATE** (DuckDB committed to a single interpretation of e.g. `03/04/2025`)
- `mixed_col` -> **VARCHAR** (cardinality 84) — sensible widening fallback, no silent coercion/data loss
- `mostly_null` -> **VARCHAR** (cardinality 1) — the >90%-null column did not break inference
- `category` -> **VARCHAR** (cardinality 3) — correctly recognized as low-cardinality
- `col_2..col_44` alternating **DOUBLE**/**VARCHAR**; row_count 100, 45+ columns exercised

### Criterion 2 — GET /schema returns v1.2 multi-table array shape (PASS)
`{"tables": [...]}` with BOTH tables present and correct flags:
`t_<uuid>_messy` (is_primary **true**) and `t_<uuid>_regions` (is_primary **false**).
Note: this was already correct in code — the doc claim that it was "stubbed against the old v1.1 single-table shape" was itself stale.

### Criterion 3 — real Redis value via redis-cli GET (**MET 2026-08-21**)
Proven against a **real** `redis-server` (`redis_version:5.0.14.1`, `tcp_port:6379`, real `redis-cli` PONG), NOT fakeredis. Test now prints `REDIS BACKEND IN USE: redis`.
`redis-cli KEYS 'schema:*'` -> `schema:3126796e-afed-427f-9499-baebeee980f5`; `TYPE` -> `string`; `STRLEN` -> `2729`; `TTL` -> `-1` (no expiry -- see session-cleanup gap).
`redis-cli GET` returned the app-written 2-table dict, including the second table in full:
```
"t_..._regions": {"cardinality": {"region_id": 6, "region_name": 4, "active": 2},
 "samples": {"region_name": ["North","South","East","West"], "active": [false, true]},
 "is_primary": false, "ddl": "CREATE TABLE t_..._regions (\"region_id\" BIGINT, \"region_name\" VARCHAR, \"active\" BOOLEAN);"}
```
Durability (fakeredis could never certify this): `BGSAVE` -> `rdb_last_bgsave_status:ok`, `dump.rdb` on disk.

**Two real defects surfaced only because this was finally run against real Redis:**
1. Memurai (ADR-011's chosen runtime) **failed to install** -- MSI 1603, root cause `SFXCA: Failed to create temp directory. Error code 5`. Pivoted to a portable `redis-server.exe` in `tools/redis/` (gitignored). See ADR-011 amendment.
2. Even with real Redis running, the client **still fell back to fakeredis** -- `redis-py` 8.1 negotiates RESP3 via `HELLO 3`, unsupported by Redis 5. Pinned `protocol=2`. Had the fallback stayed silent (as originally written), this run would have reported a green "real Redis" proof while testing an in-memory fake. See AP-9.

### Criterion 3 — superseded note (previously OPEN)
Cache round-trip verified, but served by **fakeredis**, not real Redis. Test prints its backend explicitly:
`RedisManager falling back to fakeredis (TimeoutError: Timeout connecting to server)` / `REDIS BACKEND IN USE: fakeredis`.
Cached value under `schema:{session_uuid}` is correctly keyed by BOTH table names:
`keys: ['t_9edf789d_..._messy', 't_9edf789d_..._regions']`
Blocked by ADR-011 (Memurai not yet installed). **Do not mark this criterion satisfied.**

### Criterion 4 — low-cardinality sample values (PASS)
`regions.csv` sample capture, real values: `region_name` -> 4 distinct, `active` -> BOOLEAN, 2 distinct, `region_id` -> BIGINT, 6 distinct. Low-cardinality (<20) branch fired and captured DISTINCT non-null values as specified.

### Edge case (line 50) — second file must not collide with or overwrite the primary (PASS — was previously UNTESTED)
- Distinct table names: `..._messy` vs `..._regions`
- Coexistence row counts after 2nd upload: **primary=100, second=6** — primary unchanged, both queryable
- Same-filename re-upload now returns **HTTP 409** instead of silently clobbering (new guard added)

## Defects Found And Fixed During Verification
- **[MAJOR, security] SQL injection + path traversal on the non-sandboxed path.** `read_csv_auto('{file_path}')` interpolated the user-controlled filename on `run_readwrite` — the path with NO rollback protection (ADR-010 covers only `run_sandboxed()`), so injected SQL would have **persisted**. Fixed via parameter binding (`read_csv_auto(?, header=true)`), identifier quote-escaping for CSV-derived column names, and filename sanitization before filesystem use. See ADR-012.
  - **Hard proof:** sentinel table + upload named `x'); DROP TABLE sentinel; --.csv` -> `SENTINEL SURVIVED, rows = 1` / `injection did NOT execute -> FIX CONFIRMED`. Pre-fix, the same vector was confirmed live (crafted quote changed statement boundaries).
- **[MAJOR] `redis_manager.py` could never reach real Redis** — hardcoded `fakeredis`, ignored host/port. Rewritten per ADR-011 with a real client + explicit logged fallback and an inspectable `.backend` attribute.
- **[MAJOR] `main.py:32` called the removed `get_readonly_connection()`** (ADR-003 residue) — guaranteed `AttributeError` on `GET /test-duckdb`. Repointed.
- **[MINOR] `set_json` could crash on DuckDB DATE/Decimal sample values** (not JSON-serializable). Added `default=str`.

## Remaining To Close This Task
1. ~~Install Memurai / capture real Redis proof~~ — **DONE**, see Criterion 3 above.
2. **Architect sign-off** on the fixes (ADR-012 injection, ADR-013 fail-closed validator, ADR-011 Redis client, `main.py` repoint, AP-7 idempotency, CORS). Signed off 2026-08-21 and closed by commit c28573c.

## Files Actually Changed
`backend/routers/session.py`, `backend/services/redis_manager.py`, `backend/main.py` (1 line), plus new `backend/test_multitable.py` and `backend/regions.csv` (second-table fixture).
Note: `backend/models/schemas.py` needed NO change — it already carried the multi-table shape.