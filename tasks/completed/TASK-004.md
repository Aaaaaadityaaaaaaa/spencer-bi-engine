# TASK-004

## Title
Phase 3 — Data Cleaning ("Drop & Scrub") with per-table snapshot undo/redo

## Objective
Implement the transform pipeline (dedupe, drop-null, impute-null, cast, calculated column) and per-table undo/redo/history, replacing the hardcoded stubs in `routers/session.py`. Spencer's own query construction goes through **Ibis as a compile-only layer** (ADR-007); undo/redo uses **materialized snapshots** (ADR-004). The AI-SQL path (ADR-010/013) is not touched.

## Context
The transform Pydantic models (`TransformDedupe`/`DropNull`/`ImputeNull`/`Cast`/`CalculatedColumn`, `TransformResponse`, `HistoryResponse`) already exist in `models/schemas.py`, and the four endpoints (`/transform`, `/undo`, `/redo`, `/history`) exist as stubs returning hardcoded values. This task fills the bodies. Ibis is **not yet a dependency** — adding it is part of this task (ADR-007).

## Requirements
1. `POST /sessions/{id}/transform` — discriminated by `op`; optional `table_name` query param defaults to the session's primary table:
   - `dedupe` → `SELECT DISTINCT *`
   - `drop_null` → filter rows where `column` is null
   - `impute_null` (`zero|mean|median|custom`) → `COALESCE(column, <value>)`; `custom` uses `fill_value`
   - `cast` → change `column` to `new_type`
   - `calculated_column` → add `new_column_name` = `formula`
2. `POST /sessions/{id}/undo`, `POST /sessions/{id}/redo` — per-table, independent history (optional `table_name`).
3. `GET /sessions/{id}/history` — steps, `current_step_index`, `total_steps`, `can_undo`, `can_redo` (optional `table_name`).
4. Structured ops (dedupe/drop_null/impute/cast) built as **Ibis expressions on an unbound table, compiled to DuckDB SQL, executed via `db_manager.run_readwrite`** — Ibis opens no connection of its own (ADR-007 / ARCHITECTURE.md).
5. Undo/redo via **materialized snapshots** `backup_{session}_{table}_step_{n}`, capped (ADR-004). Oldest dropped on overflow.
6. Each transform/undo/redo **increments `schema_version`** and **refreshes** the `schema:{session}` cache for that table (ARCHITECTURE.md: schema re-fetched per request, never statically cached after a transform).
7. `TransformResponse(schema_version, step, row_count)` returned with real post-transform values.

## Files Expected To Change
- NEW `backend/services/transform_service.py` — Ibis compilation, snapshot/history engine, formula validation.
- `backend/routers/session.py` — implement the four stubs; extract the schema-context computation from `analyze_and_register_table` into a reusable helper so ingestion and transform-refresh share it.
- `backend/services/redis_manager.py` — small helpers for the version counter and per-table history.
- `backend/pyproject.toml` — add `ibis-framework[duckdb]`.
- NEW `backend/test_transform.py` — idempotent proof (AP-7), prints the Redis backend (AP-9).
- `.ai/DECISIONS.md` — ADR-014 (Ibis compile-only integration + calculated-column formula validation).

## Files That Must NOT Change
`duckdb_manager.py`'s connection/transaction logic (`run_sandboxed`/`run_readwrite`) and its tests — closed by TASK-001-FIX-02/TASK-002. Transforms use `run_readwrite` only.

## Security Considerations
- **`calculated_column.formula` is user-controlled SQL on the non-sandboxed `run_readwrite` path** — the same injection class ADR-012 closed for ingestion (ADR-010's rollback does NOT cover this path). The formula MUST be validated (sqlglot, DuckDB dialect) as a **single pure scalar expression** referencing only existing columns, with no statements, no subqueries, and no forbidden (write/DDL) nodes, before it is embedded. This is a required control, not optional.
- `cast.new_type` is validated by parsing through Ibis's DuckDB type parser (rejects anything that isn't a real DuckDB type) rather than string-concatenated.
- Column identifiers are quote-escaped (`_quote_ident`).

## Acceptance Criteria (all as real pasted output)
1. Each of the 5 ops applied to a real uploaded table, showing the compiled DuckDB SQL and the real row/column/type effect (e.g. dedupe drops the known duplicate rows; cast changes the reported type; calculated column appears with correct values).
2. Undo returns the table to its exact prior state (row count + schema), redo re-applies it; shown with real counts.
3. Per-table independence: a transform + undo on table A does not affect table B in the same session.
4. `calculated_column` with a **malicious formula** (e.g. `1); DROP TABLE <sentinel>; --`) is **rejected** and the sentinel table survives — pasted proof.
5. `schema_version` increments across transforms, and `GET /schema` reflects post-transform types.
6. Snapshot cap enforced: after >cap transforms, oldest snapshot dropped, `can_undo` bounded.
7. The proof script prints `REDIS BACKEND IN USE: redis` (real Redis, not fakeredis) and is runnable twice consecutively (AP-7).

## Definition Of Done
All acceptance criteria present as real output; the four endpoints implemented; Ibis used compile-only for structured ops; calculated-column formula validated; self-review with severity grades attached. **Sign-off is the user's.**

## Status
COMPLETED — signed off by user 2026-08-21 (implementation + self-review complete; enhancements deferred to TASK-005).

## Proof
`backend/test_transform.py` — standalone, idempotent (AP-7, run twice consecutively, both green), against **real Redis 5.0.14.1** (prints `REDIS BACKEND IN USE: redis`, AP-9). All 40 checks pass, covering every acceptance criterion:
- **AC1** — each of the 5 ops applied to a real uploaded table with its compiled DuckDB SQL printed and the real effect asserted (dedupe 5→4; drop_null 5→4; impute zero/custom/mean; cast BIGINT→DOUBLE; calculated `profit = revenue - cost` = 40 for North).
- **AC2** — undo restores exact prior state (row count + revenue type back to BIGINT); redo re-applies (DOUBLE again).
- **AC3** — dedupe+undo on table A leaves table B's row count and (empty) history untouched.
- **AC4** — 4 malicious `calculated_column` formulas rejected (statement injection `1); DROP TABLE <sentinel>; --`, scalar subquery, unknown column, stacked statement); sentinel table survives.
- **AC5** — `schema_version` strictly increases per op; HTTP `GET /schema` reflects the post-cast DOUBLE type.
- **AC6** — after 15 applies, both history states and on-disk snapshots capped at 10; `can_redo` False / `can_undo` True at head.
- **AC7** — real Redis, runnable twice.
- Plus an end-to-end HTTP leg through the real FastAPI endpoints (upload → cast → schema → dedupe → undo → history → malicious→400), proving routing, the discriminated-union body, and the `TransformError`→HTTP 400 mapping.

Regression: `test_multitable.py`, `test_ingestion.py`, `test_sql_validator.py` (25/25), `test_transaction_rollback_full.py`, `test_concurrent.py` all still green after the `analyze_and_register_table` refactor and the new Ibis dependency.

## Self-Review (severity-graded)
No CRITICAL, no MAJOR.

Found and **fixed during review** (was heading toward MAJOR): the temp-swap used a fixed tmp-table name and state-mutating ops had no serialization → two overlapping transforms on one table could collide on the tmp table or lose an update. Closed with a per-`(session, table)` `asyncio.Lock` (sufficient under the mandated `--workers 1`) and a unique per-state tmp name.

Remaining, all **MINOR** (documented, not blocking):
1. **Swap is not crash-atomic.** `_materialize` is four separate `run_readwrite` calls; a hard kill between `DROP live` and `RENAME tmp` would leave the live table missing (recoverable — the prior state's snapshot still exists). A single transactional-DDL block would fix it, but that needs multi-statement transaction support `duckdb_manager` doesn't expose, and TASK-004 forbids changing `duckdb_manager`. The risky user SQL runs in `CREATE tmp` *before* anything is dropped, so a *bad transform* cannot cause this — only a crash in a microsecond window.
2. **No scalar-function allowlist in the formula validator** (ADR-014 residual). Statements, subqueries, writes, and unknown columns are all rejected; the residual is an in-expression call to a surprising built-in. Low risk for a local single-analyst tool (no persistence, no write, no rollback-path escape), noted rather than hidden.
3. **`_locks` grows one `Lock` per `(session, table)`**, never reclaimed — negligible at the 2–5-table scale, unbounded in principle over many long-lived sessions.
4. **`get_history` on an untouched table returns `current_step_index = -1`** (honest sentinel for "no state snapshotted yet"; the pristine table still exists and is snapshotted lazily on first transform).
5. **Snapshots are full table copies** (up to cap × per table). This is ADR-004's explicit simplicity-over-storage tradeoff at the stated scale, not a defect.

**Signed off by the user 2026-08-21.** Agreed enhancements (see menu below) deferred to TASK-005; this task is closed.
