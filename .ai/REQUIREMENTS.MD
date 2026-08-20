# REQUIREMENTS.md

## Functional Requirements
1. User can upload multiple CSV/Parquet files into one session; each becomes an independently-typed table
2. User can dedupe, drop/impute nulls, cast types, and add calculated columns per table, with capped undo/redo history
3. User can browse table data in a virtualized, paginated grid
4. System auto-suggests join keys across tables on upload; user must explicitly confirm before a join is usable
5. User can build charts via drag-and-drop of columns onto X/Y axes; system suggests a chart type if none is chosen
6. User can ask natural-language questions (Ctrl+K); system returns generated SQL for review before execution
7. User can define custom business-logic terms that get matched into future AI prompts
8. User can schedule a natural-language question to run recurring; can view run history
9. User can cancel a running query

## Non-Functional Requirements
- **Concurrency:** backend must not block under concurrent requests (thread pool around all DB calls); single Uvicorn worker
- **Performance:** cached repeat AI queries near-instant; fresh AI queries ~1.5–3.5s typical (dominated by LLM call, not DB)
- **Scale target:** up to ~10M rows per table; 2–5 tables per session realistic; not designed for dozens of tables
- **Security:** AI-generated SQL must never execute without (a) passing `sqlglot` validation as pure read-only, (b) running on a genuinely separate read-only connection, (c) explicit human confirmation
- **Reliability:** bounded retries (max 3) on query failure, with distinct handling for schema-miss vs. generic vs. repeated-failure vs. LLM-API-failure
- **Automation durability:** scheduled jobs must survive a backend restart (persistent job store required — currently a gap, see CURRENT_STATE.md)
- **Data hygiene:** stale sessions (uploads, tables, cache entries) must eventually be cleaned up (currently unimplemented — gap)
- **Cost control:** LLM API usage must be rate-limited per session (currently unimplemented — gap)
- **Secrets:** API keys must never be committed to the repository

## Acceptance Criteria (project-level)
- No AI-generated SQL can execute a write statement, verified by an explicit adversarial test, not just code review
- A scheduled job set to run tomorrow still runs after a backend restart today
- Uploading a messy 45+ column CSV with mixed types, ambiguous dates, and high-null columns produces a usable schema without manual correction
- Undo/redo works correctly and independently per table in a multi-table session