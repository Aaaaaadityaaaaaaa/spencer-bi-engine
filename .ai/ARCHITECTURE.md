ARCHITECTURE.md
Consolidates prior docs: Architecture v2.1, Addendum v2.2 (multi-table/joins), Addendum v2.3 (Ibis + chart suggestion). Those documents remain available for full rationale; this file is the current authoritative summary implementers must follow.

System Components
Vue 3 + TS frontend — upload UI, schema pills, TanStack-virtualized grid, ECharts drag-and-drop canvas, Ctrl+K AI palette, SQL Review Gate modal, Custom Instructions box
FastAPI backend (--workers 1) — all DuckDB calls routed through ThreadPoolExecutor/run_in_executor
DuckDB — single file (spencer.db), tables namespaced t_{session_uuid}_{tablename}. Single connection (self._conn) — DuckDB does not permit a second connection with a different read_only config to the same file in-process (see DECISIONS.md ADR-003, superseded). AI-generated SQL executes on this same connection but wrapped in a transaction that is always rolled back, per ADR-010 — pending empirical verification (TASK-001-FIX-02)
Redis — schema/bizdict/join cache, AI query cache, session/job state, APScheduler job store
LLM API (Claude/Gemini) — direct prompting, no RAG, for text-to-SQL
Data Flow (query lifecycle)
Question submitted → Redis cache check (question_hash:schema_version:bizdict_version)
Cache miss → assemble prompt (schema for all session tables, confirmed joins, matched business-logic definitions) → call LLM
Validate SQL via sqlglot (dialect: duckdb) — reject anything not pure SELECT/WITH
On DuckDB error: bounded retry (max 3), with a distinct path for "column not found" (pre-filter miss recovery) vs. generic errors vs. repeated-identical-failure
Valid SQL → SQL Review Gate → user confirms → executes on read-only connection
Result → MessagePack → frontend
Multi-Table & Joins
Multiple files per session, each an independent table; first upload is primary
Join keys auto-suggested (name+type match), never auto-applied — user must confirm via POST /joins
Joins are query-time metadata only — no materialized merge table, ever
Charting remains single-table in this version; joins apply to the NL query layer only
Query Construction: Ibis (Spencer's own queries only)
Transform ops, chart aggregation, and join-aware queries are built as Ibis expressions, compiled to SQL text, then executed through the existing connection wrapper
Ibis is a compiler only in this integration — it does not open its own connection or execute anything itself
Ibis schema must be re-fetched per request, not cached statically — stale schema after a transform (cast, calculated column) will otherwise produce incorrect SQL
This never applies to AI-generated SQL — that path is exclusively LLM → sqlglot → read-only connection, unrelated to Ibis
Reliability
Self-correction loop distinguishes: DuckDB execution errors (generic retry), "column not found" (append missing column context, retry), repeated-identical-failure (force different approach), and LLM API failures (network/timeout/rate-limit — must be handled as a distinct failure mode, not conflated with "bad SQL," since there's no SQL yet to compare for duplicate-detection)
Failed resolutions cached under fail:{...} (5 min TTL) to avoid repeat-burning tokens on an identical failing question
Security (defense in depth) — revised per ADR-010
sqlglot statement-type validation (dialect-aware: read="duckdb")
Execution wrapped in an explicit transaction that is always rolled back, unconditionally — regardless of statement type, success, or failure. Nothing on this path is ever committed. (Pending empirical verification that DuckDB's transactional DDL actually rolls back cleanly on this version — see TASK-001-FIX-02.)
Human confirmation required before any AI-generated SQL executes, regardless of validation result
Scheduling
APScheduler, in-process (fits single-worker constraint)
Job store must be persistent (Redis-backed), not the default in-memory store — in-memory jobs are lost on any restart, which directly breaks the product's stated automation goal
Scheduled runs use a pinned snapshot of schema/bizdict/joins taken at schedule-creation time, decoupled from live session TTL
Known Open Risks (see CURRENT_STATE.md for status)
Dual-connection (rw + ro) simultaneous access to one DuckDB file: implemented, not yet empirically verified
No session/data cleanup mechanism defined (uploads, tables, Redis keys accumulate indefinitely)
No LLM API cost/rate control
No file upload size/type validation
No row cap on ad-hoc /execute results
Secrets management (.env/.gitignore) not yet confirmed in place