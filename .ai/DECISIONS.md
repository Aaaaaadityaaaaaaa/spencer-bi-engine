# DECISIONS.md

### ADR-001
**Decision:** Use direct LLM prompting (Claude/Gemini) for text-to-SQL, not Vanna.ai/RAG.
**Reason:** Spencer's schema (single session, 2–5 tables realistically) fits comfortably in a prompt — RAG's retrieval advantage only activates at a scale (dozens+ tables) Spencer doesn't target.
**Alternatives:** Vanna.ai (vector-store RAG) — rejected for added infrastructure/maintenance without a corresponding benefit at this scale.
**Status:** Accepted.

### ADR-002
**Decision:** FastAPI + Vue 3, not Streamlit.
**Reason:** Preserves full-stack engineering narrative (API design, async state, frontend reactivity) for interview/portfolio purposes.
**Status:** Accepted.

### ADR-003 (SUPERSEDED — see ADR-010)
**Decision:** AI-generated SQL executes only on a genuinely separate DuckDB connection opened with `read_only=True` — never a cursor derived from the read-write connection.
**Reason:** A cursor inherits its parent connection's permissions; sharing a connection defeats the entire purpose of a second, independent defense layer. This was an actual bug caught during implementation (AP-1 in CODING_STANDARDS.md).
**Status:** SUPERSEDED. Empirically disproven — DuckDB rejects a second connection to the same file with a different `read_only` configuration while one is already open in-process (`ConnectionException: Can't open a connection to same database file with a different configuration than existing connections`). See ADR-010 for the replacement design.

### ADR-004
**Decision:** Undo/redo via per-table snapshots (`CREATE TABLE backup_step_N ...`), capped at 5–10 steps, not CTE-chaining.
**Reason:** Far easier to debug/reason about than stacked CTEs; cap bounds storage growth.
**Status:** Accepted.

### ADR-005
**Decision:** TanStack Table for grid virtualization; hand-built ECharts drag-and-drop for charting (not PyGWalker).
**Reason:** Virtualization is a solved problem — using a standard library is the correct senior-engineer move. Charting is the visual centerpiece and should stay custom, not a pre-built injected UI.
**Status:** Accepted.

### ADR-006
**Decision:** Multi-table sessions with query-time-only joins (no materialized merge table); charting stays single-table for now.
**Reason:** Extends the existing architecture with minimal disruption — undo/redo, cleaning, and the direct-prompting AI decision (ADR-001) all remain valid unchanged.
**Status:** Accepted.

### ADR-007
**Decision:** Adopt Ibis for Spencer's own query construction (transforms, chart aggregation, joins); AI-generated SQL is explicitly excluded from this.
**Reason:** Inspired by Frappe Insights' architecture. Replaces manual SQL-string building with a safer, composable API. Does not open its own connection, so it can't affect the concurrency/security model already verified in Phase 1.
**Alternatives considered from Frappe Insights and explicitly rejected:** multi-source live DB connectors (Spencer stays upload-only), a separate no-code query builder UI (redundant with drag-and-drop + NL query), persisted/saved dashboards (real new scope, not a low-effort addition).
**Status:** Accepted.

### ADR-008 (SUPERSEDED — see ADR-011)
**Decision:** Redis via Docker Compose, not a bare local instance.
**Reason:** Windows dev environment (no native Redis support), reproducibility, and a natural extension point if the whole stack is containerized later.
**Status:** SUPERSEDED by ADR-011. Docker was never actually installed in the dev environment (verified 2026-08-21: no Docker client, daemon, or install directory present), so this decision silently produced *zero* real-Redis coverage for the entire project to date — all Redis behavior was exercised against `fakeredis`. `docker-compose.yml` is retained as a valid deployment artifact.

### ADR-009
**Decision:** Adopt a formal architect / implementer separation with repo-based `.ai/` docs, task files, and severity-classified reviews.
**Reason:** Replaces the informal build-log-only process, which had repeated hygiene failures (see CODING_STANDARDS.md AP-2 through AP-5).
**Status:** Accepted.

### ADR-010
**Decision:** Replace ADR-003's dual-connection design with a single connection, using an explicit transaction that is **always rolled back, unconditionally, regardless of statement type or outcome** for all AI-generated SQL execution.
**Reason:** ADR-003 was empirically disproven (TASK-001-FIX-01) — DuckDB does not permit two simultaneous connections to the same file with different `read_only` configurations in one process. DuckDB uniquely supports transactional DDL (unlike most databases), so a guaranteed-rollback pattern gives an equivalent database-engine-level guarantee: even if `sqlglot` misses something, nothing can persist because nothing is ever committed on this path. This is a genuine second defense layer, not a downgrade to "sqlglot + human review alone" (which was the implementer's proposed fallback and was rejected as insufficient).
**Alternatives considered:** (a) single connection + rely solely on sqlglot + human review — rejected, loses defense-in-depth; (b) separate OS process for read-only access — rejected, disproportionate complexity for this project's scope.
**Migration cost:** Low — confined to `duckdb_manager.py`. No API contract or schema changes. `get_readonly_connection()`/`run_readonly()` should be renamed (e.g., `run_sandboxed()`) to avoid the misleading implication of connection-level read-only enforcement that no longer exists this way (see CODING_STANDARDS.md AP-1 update).
**Verification required before acceptance is final:** empirical proof that a rolled-back transaction genuinely leaves no trace for both DDL and DML on this DuckDB version — this is a hypothesis being tested, not an assumed fact, consistent with how ADR-003 was (correctly) tested and found wanting.
**Status:** ACCEPTED — FULLY VERIFIED. Sequential correctness proven in TASK-001-FIX-02 and concurrent correctness proven in TASK-002 (real output attached in IMPLEMENTATION_REPORT.md); DuckDB correctly isolates the transaction-scoped rollback from concurrent writes on other cursors of the same connection. The AI-query security model is closed. (Status corrected 2026-08-21: this line previously still read "Concurrency behavior not yet tested — see TASK-002" after TASK-002 had already completed — doc drift, not an open risk.)
**Residual cleanup completed 2026-08-21:** `get_readonly_connection()` was already gone from `duckdb_manager.py`, but `main.py`'s `GET /test-duckdb` diagnostic still called it (guaranteed `AttributeError`). Repointed to `get_readwrite_connection()`.

### ADR-011
**Decision:** Use **Memurai** as the real-Redis runtime for Windows development, and rewrite `redis_manager.py` to connect to a real `redis.Redis` client with an **explicit, logged `fakeredis` fallback** — exposing which backend is live via `redis_manager.backend`.
**Reason:** ADR-008 assumed Docker; Docker was never installed, so real Redis was never once exercised (see ADR-008 status). Worse, `redis_manager.py` **hardcoded `fakeredis` and ignored host/port entirely** — meaning even a running Redis could not have been reached. Memurai is a native Windows Redis-protocol server, so it removes the Docker/WSL dependency that caused the deferral in the first place. Making the fallback explicit and inspectable means a test can no longer *silently* prove nothing: every proof now states which backend served it.
**Alternatives considered:** (a) Docker Desktop — matches `docker-compose.yml` but heavier install plus licensing considerations, and it is what already failed to materialize; (b) WSL2 `redis-server` — viable, rejected as the default only because it presumes a configured WSL2; (c) keep fakeredis-only — rejected, Phases 6/7 (AI caching, APScheduler persistence) depend on real Redis semantics (TTL, eviction, restart durability) that fakeredis cannot certify.
**Consequence:** Redis-dependent proofs are **explicitly marked `fakeredis` until Memurai is installed**, rather than being presented as real-Redis proofs. TASK-003 acceptance criterion #3 (real `redis-cli GET` value) is formally OPEN, not silently satisfied.
**Status:** Accepted — client rewrite implemented and verified falling back correctly (logged `TimeoutError` → fakeredis). Real-Redis leg pending Memurai installation.

### ADR-012
**Decision:** All file paths for DuckDB ingestion are passed as **bound query parameters** (`read_csv_auto(?, header=true)`), never string-interpolated; CSV-derived column identifiers are double-quote-escaped; and uploaded filenames are sanitized before touching the filesystem.
**Reason:** `analyze_and_register_table()` interpolated the user-controlled filename into `read_csv_auto('{file_path}')` on the **non-sandboxed `run_readwrite` path** — the one path with no rollback protection (ADR-010 protects only `run_sandboxed()`). A filename containing a single quote breaks out of the SQL string literal, so injected DDL/DML would have **persisted**. Verified empirically 2026-08-21 both that DuckDB supports parameter binding here and that the pre-fix vector was live (a sentinel-table `DROP` attempt via crafted filename; post-fix the sentinel survives).
**Note:** This is the same class of gap as ADR-003 — a security control assumed to hold without an empirical test. The ADR-010 rollback sandbox does **not** cover ingestion, so ingestion needed its own control.
**Status:** Accepted — implemented and verified (sentinel survives crafted-filename `DROP`; see TASK-003 proofs).
