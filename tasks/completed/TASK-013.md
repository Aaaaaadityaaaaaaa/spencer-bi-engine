# TASK-013

## Title
Deployability hardening (single-VM, disposable data): an upload size cap + extension allowlist (3 layers),
a `session:{uuid}` sliding-TTL liveness marker, a periodic cleanup sweep that reclaims dead sessions'
DuckDB tables + `uploads/` dirs + Redis keys, DuckDB `memory_limit`/`temp_directory` applied at startup,
and a central `config.py` — all through the existing wrappers, with the frozen `duckdb_manager.py`
untouched.

## Objective
Make Spencer safe to run unattended on one long-lived VM/VPS without the disk filling and without an
unbounded upload knocking the box over. Today `uploads/` and `spencer.db` grow forever (there is no cleanup
mechanism), any file of any size/type is accepted, and the documented `PRAGMA memory_limit` was never
actually applied. This task closes those three gaps as a coherent lifecycle: a session is declared **alive**
by a Redis marker with a sliding TTL, a background sweep reclaims everything a **dead** session owned, and
uploads are gated on size (three layers) and extension before they can persist — with sensible operator
knobs centralized in one config module.

## Context
Deployment shape was locked with the user over one decision round: **deploy target = a single VM/VPS with a
persistent disk; uploaded data = disposable (fine to lose on restart).** The user's explicit standing
instruction: *"make sure the TTL/cleanup sweep is still in scope somewhere in the deployment plan — it's
cheaper to build now than to discover the disk is full."* That directly motivates parts B + C below.

The disposable-data posture is what makes the design simple and safe: because losing uploaded data on
restart is acceptable, the sweep can reclaim aggressively, and the fact that the portable `redis-server`
does not survive a reboot (ADR-011 amendment) becomes a *feature* — when Redis is wiped, all liveness
markers vanish and the next sweep reclaims every `uploads/` dir + its tables, i.e. a clean slate rather than
a leak.

**Two distinct caps must not be conflated:** the pre-existing `/execute` **result-row** cap (`MAX_ROWS=1000`,
in `routers/ai.py`, TASK-012) is unrelated to this task's **upload-byte** cap.

**Recorded divergences from the plan (not hidden):**
- The plan named a `session.py`; the session/ingestion router in this tree is `routers/session.py` and the
  edits landed there.
- The streaming byte-count backstop cannot be provoked over HTTP with `curl` (curl always sets an honest
  `Content-Length`, so the middleware catches it first). It is instead proven by a standalone duck-typed
  `FakeUpload` calling `session._persist_upload` directly with the server stopped (§D) — the honest way to
  exercise the chunked/absent/lying-Content-Length branch.
- Baseline = the still-unsigned **TASK-008/009/010/011/012** working tree (itself on commit `a3c7162`).
  None of those is committed or signed off, so this work sits on top of them; §F separates TASK-013's own
  files from the inherited changes.

## Requirements
1. **Central config** (`backend/config.py`, new) — read env once at import (matches the existing
   `SPENCER_CORS_ORIGINS` convention): `MAX_UPLOAD_MB`/`MAX_UPLOAD_BYTES`, `ALLOWED_EXTENSIONS` (frozenset,
   dot-stripped, lowercased), `UPLOAD_CHUNK_BYTES`, `SESSION_TTL_HOURS`/`_SECONDS`,
   `SWEEP_INTERVAL_MIN`/`_SECONDS`, `SWEEP_GRACE_MIN`/`_SECONDS`, `DUCKDB_MEMORY_LIMIT`, `DUCKDB_TEMP_DIR`,
   `UPLOADS_DIR`, plus `ext_of()` / `is_allowed_upload()`.
2. **Upload guardrails** (`routers/session.py`, edit) — `_reject_disallowed_type(filename)` raises **415**
   before any bytes persist (fails closed on no extension); `_persist_upload` streams the spooled body in
   `UPLOAD_CHUNK_BYTES` chunks counting bytes, and on exceeding `MAX_UPLOAD_BYTES` raises **413** and
   `os.remove`s the partial file. `create_session` + `upload_table` call `_reject_disallowed_type` then
   `touch_session(uuid, TTL)` **before** `_persist_upload` (marker before dir — anti-race).
3. **Content-Length early reject + TTL slide** (`main.py`, edit) — an `@app.middleware("http")` deploy guard
   that (a) early-returns a JSON **413** when an upload endpoint's `Content-Length` exceeds the cap, and
   (b) slides the liveness TTL (`refresh_session`) on any `/sessions/{uuid}/...` request. Registered
   **before** `CORSMiddleware.add_middleware` so CORS stays outermost and the early 413 still carries
   `Access-Control-Allow-Origin`.
4. **Redis liveness helpers** (`services/redis_manager.py`, edit — NOT frozen) — `touch_session`
   (SET+EXPIRE, creates/refreshes), `refresh_session` (EXPIRE-only — no resurrection of a reaped/bogus
   uuid), `session_alive` (EXISTS), `purge_session` (delete the session's `schema`/`bizdict`/`joins`/
   `schema_version`/`bizdict_version`/`session` keys).
5. **Cleanup sweep** (`services/cleanup_service.py`, new) — `sweep()` snapshots the DuckDB catalog **once**
   via a static `information_schema.tables` query, iterates `uploads/`, skips non-dirs, skips dirs within
   `SWEEP_GRACE_SECONDS`, skips live-marked sessions, and for each dead session drops its prefix-matched
   tables, `rmtree`s its dir, and `purge_session`s its keys; one `CHECKPOINT` if anything was reclaimed.
   Idempotent. `storage_report()` for `GET /admin/storage`. `sweep_loop()` runs every
   `SWEEP_INTERVAL_SECONDS`, re-raising `CancelledError`.
6. **Startup PRAGMA hardening** (`main.py`, edit) — apply `PRAGMA memory_limit` (regex-validated operator
   value) + optional `temp_directory` via `run_readwrite` on startup; launch `sweep_loop()` as an asyncio
   task, cancel it on shutdown.
7. **Admin endpoints** (`routers/admin.py`, edit) — `POST /admin/sweep` → `sweep()`; `GET /admin/storage`
   → `storage_report()`; the existing `kill-query` untouched.
8. **`.env.example`** (edit) — document the new knobs; move `MAX_UPLOAD_MB` out of the "not yet enforced"
   block; keep `SPENCER_MAX_LLM_CALLS_PER_SESSION` in the Phase-8-gap block.
9. **Proof** (`backend/test_cleanup.py`, new) — real-Redis, idempotent, AP-9 backend print; DEAD reaped /
   LIVE + within-grace GRACE preserved / re-sweep stable.

## Files Expected To Change
- **Backend new:** `backend/config.py`, `backend/services/cleanup_service.py`, `backend/test_cleanup.py`.
- **Backend edit:** `backend/main.py` (deploy-guard middleware + startup PRAGMA + sweeper task),
  `backend/routers/session.py` (415 type gate + streaming 413 cap + `touch_session`),
  `backend/routers/admin.py` (`/sweep` + `/storage`), `backend/services/redis_manager.py` (liveness
  helpers).
- **Config/docs:** `../.env.example` (deployment knobs); `.ai/CURRENT_STATE.md` (full regen — AP-4),
  `.ai/ARCHITECTURE.md` (cleanup + upload validation now defined), `.ai/DATABASE.md` (session TTL now
  defined; `memory_limit` now applied).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; every DROP / CHECKPOINT / PRAGMA /
  `information_schema` read routes through the existing `run_readwrite`. Verified: `git diff --` empty (§F).
- **`backend/services/sql_validator.py`** — not on this path; `git diff --` empty (§F).
- **The `POST /chart` MessagePack stub** and **`POST /queries/{id}` poll stub** — deferred paths, untouched.
- **`DELETE /sessions/{uuid}`** — left as the pre-existing stub (AP-2); wiring it to a shared reclaim path
  is a clean follow-up now that `cleanup_service` exists (self-review finding 5), out of this task's scope.
- **Canvas (TASK-011) / DataGrid virtualizer (TASK-006) / Query Engine (TASK-012)** — not on this path.
- **`README.md`** — not touched; sign-off (and any roadmap update) is the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **The filesystem-derived uuid NEVER reaches SQL (ADR-012 / AP-8).** `cleanup_service.sweep` reads the
  untrusted `uploads/{entry}` directory name but never interpolates it into a query. It snapshots DuckDB's
  own catalog (`SELECT table_name FROM information_schema.tables`, a static string), derives the identifier
  prefixes `t_{uuid_}_` / `backup_{uuid_}_` in Python, filters the **catalog** names by those prefixes, and
  only ever `DROP`s catalog-sourced, `_quote_ident`-escaped identifiers. This matters most because
  reclamation runs on `run_readwrite` — the path with **no** rollback — so there is no safety net; the
  control is that no user/filesystem value is ever in the SQL text. Verified: `duckdb_manager.py` diff empty.
- **Upload size cap is defense-in-depth across three layers, honest about where the real gate is.** (1) An
  nginx `client_max_body_size` in front is the only truly pre-server gate (documented deploy step, not
  code — Starlette's `UploadFile` spools the whole body before the route runs). (2) A `Content-Length`
  middleware early-rejects the common honest-browser case with **413** before the body is read. (3) A
  streaming byte-count backstop in `_persist_upload` catches chunked / absent / lying `Content-Length`,
  removes the partial file, and raises **413**. §B/§D prove layers 2 + 3.
- **Extension allowlist fails closed** on `POST /sessions` and `POST /sessions/{id}/tables`:
  `_reject_disallowed_type` raises **415** before any bytes persist, and a filename with **no** extension is
  rejected (empty ext ∉ `ALLOWED_EXTENSIONS`). §B: `.json` / `.txt` → 415, no dir/table created.
- **PRAGMA operator knob is regex-validated.** `SPENCER_DUCKDB_MEMORY_LIMIT` is matched against
  `^\s*\d+(\.\d+)?\s*(%|[KMGT]?i?B)?\s*$` before it is placed in the PRAGMA literal, so a malformed env
  value can't break out of the string; `temp_directory` is single-quote-escaped. A bad value is logged and
  ignored, never executed.
- **No session resurrection.** `refresh_session` is EXPIRE-only, so the TTL-slide middleware firing on a
  request to a reaped or bogus uuid is a no-op — it cannot recreate a marker and thereby shield orphaned
  storage from the sweep. §C: a GET to a bogus uuid → 404 and no marker created.
- **Grace window prevents a mid-upload reap.** A dir touched within `SWEEP_GRACE_SECONDS` is never reaped,
  so an in-flight upload whose marker/table doesn't exist yet is safe. §-test: the GRACE fixture (fresh
  mtime, no marker) survives both sweeps.
- **No secrets, no new external calls.** All new endpoints are same-origin admin routes; no API keys are
  touched; the AI path is not part of this task.

## Acceptance Criteria
1. `test_cleanup.py` green (real Redis, AP-9) **twice** back-to-back: DEAD session reaped (table + dir +
   schema key), LIVE session preserved (marker + table + dir + schema key), within-grace GRACE preserved;
   the second sweep changes nothing.
2. Upload type gate: `.json` / `.txt` → **415** with no `uploads/` dir and no table created; a `.csv` within
   the cap → **200**.
3. Upload size cap: a body whose `Content-Length` exceeds the cap → **413** from the middleware, with no dir
   and no table created; the streaming backstop → **413** + the partial file removed when `Content-Length`
   is bypassed.
4. TTL slide: a `/sessions/{uuid}/...` request increases the `session:{uuid}` TTL back toward the full
   window; a request to a bogus uuid → **404** and creates no marker.
5. Startup PRAGMA effective: `GET /admin/storage` reports the applied `duckdb_memory_limit` (proving the
   startup PRAGMA ran on the live connection), plus `live_sessions` / `orphan_dirs` / `table_count`.
6. `POST /admin/sweep` reclaims dead sessions while leaving a live session's table + dir + marker intact.
7. Scope: `git diff -- backend/services/duckdb_manager.py` and `... sql_validator.py` both empty; the
   `/chart` + `/queries/{id}` stubs and the `DELETE /{uuid}` stub unchanged.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (real Redis + real DuckDB
+ real backend); the frozen `duckdb_manager.py` and `sql_validator.py` unchanged; self-review with severity
grades attached. **Sign-off is the user's — I do not self-close this task, nor self-close TASK-008/009/010/
012.** (`.ai/CURRENT_STATE.md` was regenerated per AP-4 as part of this task's doc scope; `README.md` is
untouched.)

## Status
AWAITING USER SIGN-OFF. Implementation + self-review complete; **all paths verified live against real
Redis + real DuckDB** (§A–§F). No implementation bug was found during verification. One documented
Low-severity boundary (orphan tables with no `uploads/` dir; dev/test-only) and one clean follow-up
(`DELETE /{uuid}` wiring) are recorded below rather than expanded late without sign-off.

## Proof
Captured this session with the full stack live (real `redis-server.exe` on `:6379`, backend `:8000`).
The one running backend had to be restarted onto this task's code (its DuckDB single-writer lock otherwise
blocks `test_cleanup.py`; DuckDB is single-file, single-writer).

### A. Cleanup sweep — `test_cleanup.py` 13/13, twice, real Redis (AC1, AP-9)
```
REDIS BACKEND IN USE: redis
sweep #1: {'sessions_reaped': …, 'tables_dropped': …, 'dirs_removed': …, 'bytes_estimated': …}
PASS: DEAD table dropped            PASS: DEAD dir removed        PASS: DEAD schema key purged
PASS: LIVE table kept               PASS: LIVE dir kept           PASS: LIVE marker kept
PASS: LIVE schema key kept          PASS: GRACE table kept (within grace)
PASS: GRACE dir kept (within grace) PASS: sweep reaped >=1 session
sweep #2: {'sessions_reaped': 0, 'tables_dropped': 0, 'dirs_removed': 0, 'bytes_estimated': 0}
PASS: DEAD still gone after re-sweep   PASS: LIVE still intact after re-sweep
PASS: GRACE still intact after re-sweep
13/13 assertions passed  (redis backend: redis)
```
The **first live run also reclaimed real cruft**: 63 orphaned session dirs / 56 tables / ~48 MB of
pre-existing `uploads/` + `spencer.db` accumulation from earlier test scripts — the exact leak this task
exists to stop. The immediate re-run reaped 0 (idempotent).

### B. Upload guardrails over live HTTP (AC2, AC3)
```
POST /sessions  file=probe.json  -> 415   (no uploads/<uuid> dir, no table)   # extension allowlist, fail-closed
POST /sessions  file=probe.txt   -> 415   (no dir, no table)
POST /sessions  file=small.csv   -> 200   (accepted; dir + table created)
POST /sessions  file=big.csv (2.9 MB, cap overridden to SPENCER_MAX_UPLOAD_MB=1) -> 413 (middleware); no dir, no table
```
The size case used a 1 MB cap override against a 2.9 MB file so the reject is deterministic without
shipping a 100 MB fixture; the middleware `Content-Length` branch fires and the route never runs.

### C. TTL slide + no-resurrection + storage report (AC4, AC5)
```
GET /sessions/{live}/schema   -> session:{live} TTL slid 86348 -> 86400   (activity refreshes the window)
GET /sessions/{bogus}/schema  -> 404, and EXISTS session:{bogus} == 0     (refresh_session did NOT create a marker)
GET /admin/storage -> { duckdb_memory_limit: "3.7 GiB", live_sessions: 1, orphan_dirs: 0, table_count: 8, … }
```
`duckdb_memory_limit:"3.7 GiB"` proves the **startup** `PRAGMA memory_limit` took effect on the live
connection (DuckDB reports the decimal `4GB` knob as its GiB equivalent, 4·10⁹ B ≈ 3.7 GiB — expected, not
a bug). `orphan_dirs:0` / `live_sessions:1` reflect the post-sweep clean state.

### D. Streaming backstop — the Content-Length-bypass branch (AC3)
With the server stopped, a standalone duck-typed `FakeUpload` (a `.file` yielding chunks, no honest
`Content-Length`) was passed to `session._persist_upload`:
```
_persist_upload(oversize FakeUpload) -> HTTPException 413   and the partial file was os.remove'd (not left on disk)
```
This is the only faithful way to exercise the chunked/absent/lying-Content-Length path, since `curl` always
sets `Content-Length` and layer 2 would catch it first.

### E. Manual sweep leaves a live session intact (AC6)
```
POST /admin/sweep  (with one live-marked session present) -> live session's table + dir + marker all still present
```

### F. Scope (AC7)
```
$ git diff -- backend/services/duckdb_manager.py   → (empty)     # frozen manager untouched
$ git diff -- backend/services/sql_validator.py    → (empty)     # not on this path
routers/query.py  POST /chart                      → still `return b""`                 # deferred stub intact
routers/ai.py     POST /queries/{id}               → still the completed-stub shape     # deferred stub intact
routers/session.py DELETE /{uuid}                  → still the pre-existing stub         # AP-2, follow-up below
```

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Low — coverage boundary, documented] Orphan DuckDB tables with no `uploads/` dir are not reclaimed.**
   The sweep is **dir-indexed** — it reclaims tables *by walking `uploads/`*. In production every table is
   created through ingestion, which always creates both a dir and a marker, so no such orphan arises in
   normal operation. But scripts that `CREATE TABLE` directly (and the `table_count:8` vs `live_sessions:1`
   seen in §C) leave tables with no dir, which this sweep will not touch. **Follow-up (needs sign-off, since
   it widens the DROP surface):** a catalog-driven pass that reverse-maps `t_{uuid}_` / `backup_{uuid}_`
   names to a uuid and drops any owned by neither a live marker nor a dir. I chose to document this rather
   than expand the DROP surface late in verification. Recorded in `.ai/CURRENT_STATE.md` "Known Gaps".
2. **[Low — ops dependency, by design] The airtight upload gate is nginx, not the app.** Starlette spools
   the whole request body before the route runs, so the two app-level checks (Content-Length 413, streaming
   413) are defense-in-depth, not the true ceiling. `client_max_body_size` **must** be set on the proxy to
   match `SPENCER_MAX_UPLOAD_MB` on a real deploy. Documented in `.env.example` and `.ai/ARCHITECTURE.md`.
3. **[Info — proof method] The streaming backstop is proven off-HTTP.** Because `curl` always sends an
   honest `Content-Length`, the middleware (layer 2) always wins over HTTP; the backstop (layer 3) is
   exercised by a standalone duck-typed call (§D). This is the correct way to reach that branch, but it is
   not an end-to-end HTTP proof of layer 3 — noted for honesty.
4. **[Info — disposable-data consequence, intended] A Redis wipe reclaims everything on the next sweep.**
   The portable `redis-server` doesn't survive a reboot; when it restarts empty, all liveness markers are
   gone, so the next sweep treats every `uploads/` dir as dead and reclaims it. For the locked
   disposable-data posture this is the intended clean-slate behavior, not a defect — but it is a real
   coupling worth stating: **do not** point this cleanup design at data you must keep across a Redis restart
   without first giving Redis persistence/HA (relevant before Phase 7 APScheduler is trusted).
5. **[Info — clean follow-up] `DELETE /sessions/{uuid}` is still a stub.** It returns
   `{"status":"deleted"}` without reclaiming anything (pre-existing, AP-2 — out of this task's approved
   scope). Now that `cleanup_service` exists, wiring DELETE to a shared per-session reclaim (drop tables +
   rmtree dir + `purge_session`) is a small, clean follow-up. Flagged, not done.
6. **[Info — no test suite for the HTTP guard cases] The 415/413/TTL/storage checks were run live, not
   committed as a pytest.** `test_cleanup.py` covers the sweep/TTL/grace logic deterministically; the
   HTTP-layer guards (§B–§E) were verified interactively against the live backend. A committed
   `test_upload_guards.py` (spinning the app with `TestClient`) would lock them in — sensible follow-up,
   consistent with the missing `test_aggregate.py` noted for TASK-011.
7. **[Info — carried forward] Builds on the unsigned TASK-008/009/010/011/012 working tree** (itself on
   `a3c7162`). This task's own diff is the file set in §F / "Files Expected To Change"; shared files show
   cumulative diffs because none of the prior tasks is committed. I have **not** self-closed any of them.

**Net:** the storage lifecycle — a session declared alive by a sliding-TTL marker, a dead session's tables
+ dir + Redis keys reclaimed by an idempotent sweep (which cleared 63 real orphans / ~48 MB on its first
run), uploads gated on size across three layers and on extension before any bytes persist, and
`memory_limit` actually applied at startup — is proven end-to-end against real Redis + real DuckDB, with the
filesystem uuid provably kept out of all SQL and the frozen `duckdb_manager.py` + `sql_validator.py`
untouched. The honest edges are a documented dev-only coverage boundary (finding 1), the by-design reliance
on nginx for the true upload ceiling (finding 2), and one off-HTTP proof (finding 3). I have **not** marked
this task closed — **awaiting your sign-off.**
