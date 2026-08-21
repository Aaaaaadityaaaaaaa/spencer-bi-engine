# TASK-005

## Title
Data Cleaning v2 — additional transform ops, predicate filtering, and dry-run preview

## Objective
Extend the Phase 3 cleaning pipeline (TASK-004) with the analyst-facing ops and
efficiency features deferred at TASK-004 sign-off, keeping the same architecture:
Ibis compile-only for structured ops (ADR-007/014), sqlglot fail-closed validation
for any user-authored expression (ADR-013/014), snapshot undo/redo (ADR-004), and
the `run_readwrite` path only (`run_sandboxed` untouched).

## Context
TASK-004 shipped the five core ops (dedupe, drop_null, impute_null, cast,
calculated_column) plus per-table snapshot undo/redo/history and was signed off
2026-08-21. During sign-off review the following gaps were identified as real but
out of TASK-004's spec, and explicitly deferred here rather than tacked on
(AP-2 — no silent scope creep).

## Requirements
New transform ops (all discriminated by `op`, reusing TASK-004's endpoint /
undo-redo / history plumbing):
1. `drop_column` — remove a column (Ibis `.drop()`).
2. `rename_column` — rename a column (Ibis `.rename()`); reject collision with an
   existing name.
3. `dedupe_subset` — dedupe on a chosen key-column subset, keeping first/last
   (DuckDB `DISTINCT ON` / equivalent), not whole-row `DISTINCT *`.
4. String normalization on a column: trim whitespace, change case
   (upper/lower/title), and find-replace (incl. mapping a token like `"N/A"` to
   NULL). Ibis string ops.
5. `filter_rows` — keep/remove rows matching a user predicate (e.g. `revenue > 0`).
   **SECURITY:** the predicate is user SQL on the non-sandboxed path — it MUST reuse
   the same fail-closed scalar-expression validator as `calculated_column` (single
   boolean scalar expression, existing columns only, no statements/subqueries/writes),
   re-serialized from the AST. Do not open a second, weaker validation path.
6. `impute_null` strategy `mode` — most-frequent value, so a null *categorical*
   column has a non-custom option (mean/median are numeric-only).

Efficiency / robustness:
7. Dry-run / preview: compile the op's SELECT and return the projected row-count
   delta (and a small sample) **without** materializing or snapshotting, so the UI
   can show "this will drop N rows" before the user commits.
8. Close the formula/predicate **function-allowlist** residual from ADR-014:
   whitelist an explicit set of scalar functions; reject in-expression calls to
   anything outside it. This closes the last theoretical gap noted in the TASK-004
   self-review.

## Files Expected To Change
- `backend/services/transform_service.py` — new op compilation branches, the shared
  expression validator extended with the function allowlist, a preview helper.
- `backend/models/schemas.py` — new discriminated `TransformParam` members + a
  preview response model.
- `backend/routers/session.py` — a preview endpoint (e.g.
  `POST /sessions/{id}/transform/preview`); the existing four endpoints unchanged in
  contract.
- `backend/test_transform.py` (or a sibling) — new proofs, idempotent (AP-7), prints
  the Redis backend (AP-9).
- `.ai/DECISIONS.md` — amend ADR-014 (function allowlist now closed) or add a new ADR
  for the predicate-filter validation reuse.

## Files That Must NOT Change
`duckdb_manager.py` connection/transaction logic (`run_sandboxed`/`run_readwrite`) —
closed by TASK-001-FIX-02/TASK-002. Transforms use `run_readwrite` only. The AI-SQL
path is untouched.

## Security Considerations
- `filter_rows` predicate and `calculated_column` formula share **one** fail-closed
  validator; the function allowlist (req. 8) applies to BOTH. A weaker or duplicated
  predicate path would reopen the ADR-012/013 injection class on the non-sandboxed
  path.
- `rename_column`/`drop_column` operate on identifiers only — quote-escape, never
  interpolate raw.

## Acceptance Criteria (all as real pasted output)
1. Each new op applied to a real table, with its compiled DuckDB SQL and real effect.
2. `filter_rows` with a malicious predicate rejected (sentinel survives), matching the
   TASK-004 formula proof.
3. Function allowlist: an in-expression call to a non-whitelisted built-in is rejected;
   whitelisted arithmetic/string functions still pass.
4. Dry-run returns the correct row-count delta **without** changing the table or adding
   a history step (verified: history length unchanged, row count unchanged after
   preview).
5. Undo/redo still round-trips across the new ops.
6. Proof idempotent and prints `REDIS BACKEND IN USE: redis` (AP-7/AP-9).

## Definition Of Done
All acceptance criteria as real output; new ops reuse the TASK-004 engine (Ibis
compile-only + snapshot undo/redo); predicate and formula share one fail-closed
validator with the function allowlist closed; self-review with severity grades
attached. **Sign-off is the user's.**

## Status
DRAFT — scope agreed at TASK-004 sign-off 2026-08-21; not yet started.
