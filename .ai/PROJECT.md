# PROJECT.md

**Product name:** Spencer

**Purpose:** An in-process, columnar business intelligence tool. Upload CSV/Parquet files, clean them visually, build charts by dragging columns onto axes, and ask natural-language questions (including cross-table joins) converted to SQL and executed only after human review.

**Problem being solved:** Self-service BI without a heavy server-client data warehouse stack — full analyst workflow (ingest → clean → visualize → query) on a single machine, at demo/portfolio scale.

**Target users:** A single analyst per session — not multi-tenant. Built as a portfolio/interview project with a genuine automation use case (scheduled recurring queries).

**Core functionality:**
- Multi-file upload per session, each file its own table
- Visual data cleaning with per-table undo/redo (snapshot-based, capped history)
- Drag-and-drop chart building (ECharts) with auto chart-type suggestion
- Auto-detected, user-confirmed joins across tables
- Natural-language → SQL via direct LLM prompting (Claude/Gemini), validated and human-approved before execution
- Scheduled/recurring natural-language queries (APScheduler)

**Non-goals (explicit):**
- Not multi-tenant SaaS
- Not connected to live external databases — upload-only
- No BYOK — single server-side API key
- No Vanna.ai / RAG / vector store, at any table count within target scale
- No Streamlit — full decoupled FastAPI + Vue 3
- No persisted/saved dashboards in this version
- No separate no-code query builder UI (redundant with drag-and-drop + NL query)
- Not horizontally scalable — DuckDB single-writer-file model is accepted, not a bug

**Technology stack:** DuckDB, FastAPI (`--workers 1`), Vue 3 + TypeScript + Tailwind, TanStack Table, Apache ECharts, Ibis (query construction), sqlglot (SQL validation), Redis (cache + job store), APScheduler, Claude/Gemini API (direct prompting).

**Current project maturity:** Early build — Phase 1 (skeleton/concurrency/Redis) scaffolded; the read-only DB connection fix is implemented but **not yet verified** (see CURRENT_STATE.md — this is the active blocker).

**Important constraints:** Single DuckDB file/process, single Uvicorn worker (DuckDB's file-lock model). Realistic table count per session: 2–5, not dozens. Development on Windows (`e:/SPENCER V1`), Redis via Docker Compose.
