# TASK-019

## Title
**Wave 1b — Fill-down + outlier flagging.** The two ops TASK-018 explicitly deferred, delivered as structured
transform ops riding the existing op-agnostic apply / preview / undo / redo / history plumbing: **#7 fill-down /
fill-up** (⬜→✅) and **outlier flagging** (⬜→✅). Both close the last Table-cleaning gap BACKLOG sequenced
after Wave 1. `fill_down` is the one op in the toolkit that needs an **ordered** window, so it uses a distinct
compile path (raw SQL over DuckDB's `rowid`) — the reason Wave 1 held it back; `flag_outliers` is a normal
full-frame Ibis window expression.

## Objective
`tasks/BACKLOG.md` (verified 2026-08-22) lists **#7 fill-down / outlier** as the item to build "then" (right
after Wave 1's #3–#6). The TASK-018 plan deferred it to **Wave 1b** with a stated reason: fill-down needs a
stable *row order* to carry the last/next non-null value, but `_compile_structured` is deliberately **set-based
with no rowid / ORDER BY column** — a genuinely different mechanism, not the add-a-transform pattern the other
ops share. Wave 1b delivers both:
- **#7a fill_down** — forward (`down`) / backward (`up`) fill of nulls in a column, in stable row order.
- **#7b flag_outliers** — add a boolean column marking statistical outliers (z-score) in a numeric column.

## Context
Structured ops live in `transform_service._compile_structured`, which builds an **unbound** `ibis.table`
expression and returns `ibis.to_sql(expr, dialect="duckdb")` — **synchronous, no DB access** (Ibis is a
compiler here, never a connection — ADR-007); the compiled SELECT then runs via `db_manager.run_readwrite`.

**The fill-down mechanism (why it is not `_compile_structured`).** An unbound Ibis schema has no row identity,
so an ordered window (`LAST_VALUE … OVER (ORDER BY …)`) cannot be expressed there. But the **materialized**
base table exposes DuckDB's `rowid` pseudocolumn — the `/data` endpoint already reads with `ORDER BY rowid`,
so `rowid` *is* the table's stable order. `fill_down` therefore compiles to **raw SQL** built only from the
quoted, schema-validated column name:
```sql
-- down: carry the last non-null forward
SELECT * REPLACE (
  COALESCE("g", LAST_VALUE("g" IGNORE NULLS)
    OVER (ORDER BY rowid ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS "g")
FROM <table>
-- up: FIRST_VALUE(... IGNORE NULLS) OVER (ORDER BY rowid ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
```
`SELECT *` does **not** project the `rowid` pseudocolumn, so the output schema is preserved exactly (verified
live: preview columns stay `[id, region, revenue]`). `_compile_op` routes `fill_down` to
`_build_filldown_sql` and everything else stays on the existing path (`calculated_column`→`_build_calc_sql`,
`filter_rows`→`_build_filter_sql`, else→`_compile_structured`).

**The outlier mechanism.** `flag_outliers` is a normal full-frame Ibis window expression —
`(col - col.mean()).abs() > (threshold * col.std())` — which compiles to
`ABS(x - AVG(x) OVER (…)) > (STDDEV_SAMP(x) OVER (…) * threshold)`, yielding a BOOLEAN column. Sample-stddev
math bounds a lone outlier's z-score at `(n-1)/√n`, so the test fixture uses **n = 12** (eleven 100s + one
200 ⇒ z ≈ 3.175 > 3.0) to make "exactly one row flagged at threshold 3.0" deterministic.

Because apply / preview / undo / redo / history are op-agnostic, both ops get preview, undo/redo, and history
**for free**, and **no router change** was needed: the body passes through the `TransformParam` union verbatim.

## Requirements (per feature)
### #7a fill_down (new op — raw-SQL ordered window)
1. **Model** `TransformFillDown` — `op`, `column`, `direction: Literal["down","up"]="down"`.
2. **Compile** (`_build_filldown_sql`) — validate `column` exists (else `TransformError`); emit the
   `SELECT * REPLACE (COALESCE(col, LAST_VALUE/FIRST_VALUE(col IGNORE NULLS) OVER (ORDER BY rowid …)) AS col)`
   above. Only the **quoted, schema-validated** identifier is interpolated; `direction` selects a fixed SQL
   template. In-place (row count unchanged); leading (down) / trailing (up) nulls with no value to borrow stay
   null.

### #7b flag_outliers (new op — full-frame Ibis window)
3. **Model** `TransformFlagOutliers` — `op`, `column`, `new_column_name`, `method: Literal["zscore"]="zscore"`,
   `threshold: float=3.0`.
4. **Compile** (`_compile_structured` branch) — guard source is numeric
   (INT/DECIMAL/DOUBLE/FLOAT/REAL/NUMERIC); validate `new_column_name` (non-empty, not colliding, via the
   `_build_calc_sql` collision guard); reject unknown method; require `threshold > 0`;
   `is_out = (col - col.mean()).abs() > (threshold * col.std())`; `expr = t.mutate(**{new: is_out})`.

### Shared plumbing / frontend
5. Add both models to the `TransformParam` `Union` (discriminated on `op`; no other change).
6. **`types.ts`** — `FillDownOp` + `FlagOutliersOp` interfaces, the `FillDirection` / `OutlierMethod`
   string-literal unions, both added to the `TransformOp` union. snake_case matches the wire.
7. **`OpDialog.vue`** — `OP_META` entries; `form` fields (`fillDirection`, `outlierMethod`, `threshold`);
   reset-watch defaults; column-picker list gains both ops; `buildOp` cases (the switch is **TS-exhaustive over
   `OpKind`**, so each new union member *forces* a case — the compile-time guarantee); a `fill_down` direction
   `<select>` and a `flag_outliers` block (method select + positive-threshold number input). The **generic
   preview panel is reused as-is**.
8. **`CleaningToolbar.vue`** — `Fill down / up` in the **Nulls** group; `Flag outliers` in the **Derive**
   group (`ArrowDownToLine` / `Flag` from `@lucide/vue`).
9. **`DataGrid.vue`** — both ops added to `COLUMN_OPS` so the per-column ⋮ menu can pre-scope the source column.
10. **Strict build** — `vue-tsc -b && vite build` clean; Table bundle stays ECharts-free.

## Files Expected To Change
- **Backend edit:** `backend/models/schemas.py` (+2 models, +2 in the union), `backend/services/transform_service.py`
  (`flag_outliers` branch in `_compile_structured`; new `_build_filldown_sql`; `fill_down` route in `_compile_op`).
- **Frontend edit:** `frontend/src/types.ts` (contract), `frontend/src/components/OpDialog.vue` (forms + buildOp +
  reset defaults), `frontend/src/components/CleaningToolbar.vue` (two ribbon buttons),
  `frontend/src/components/DataGrid.vue` (COLUMN_OPS).
- **Tests:** `backend/test_transform_v2.py` (`task019_main` structured proof + HTTP end-to-end cases).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — only `run_readwrite` is used, transitively.
- **`backend/services/transform_service.py` op-agnostic pipeline** — apply / preview / undo / redo / materialize
  internals untouched; `fill_down` only *adds* a route in `_compile_op` and `flag_outliers` only *adds* a branch
  to `_compile_structured`.
- **`backend/routers/session.py`** — apply/preview handlers pass the body through the `TransformParam` union
  verbatim; the new ops route by `op` with **no router edit**. *(Carries an unrelated TASK-013 working-tree diff
  in its upload routes only.)*
- **`backend/services/sql_validator.py`** — gates *AI-generated* SQL; correctly not on this structured path.
- **`api.ts` / `useSession.ts` / `TableView.vue`** — the op travels verbatim; `openOp(req)` forwards the
  `OpRequest` untouched.
- **`README.md` / `.ai/CURRENT_STATE.md`** — sign-off + roadmap are the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client-assembled SQL (ADR-012).** `flag_outliers` is a structured Ibis expression compiled server-side
  from typed params + a column name validated against the live schema — **no user string is interpolated**.
  `fill_down` builds raw SQL, but the **only** value interpolated is the source column name, first checked to
  exist in the live schema and then passed through `_quote_ident`; `direction` selects one of two **fixed** SQL
  templates (no user text). No free-form string reaches SQL on either path; `calculated_column` / `filter_rows`
  (the sqlglot-allowlisted string paths, ADR-013/015) are untouched.
- **Fail-closed → 400, never 500.** Unknown/missing column, non-numeric source (flag_outliers), empty/colliding
  `new_column_name`, unknown method, `threshold ≤ 0`, bad direction → `TransformError` → HTTP **400** with **no
  mutation**. Apply runs under the temp-swap materialize (ADR-004): a compile/exec failure drops the tmp table
  and never touches the live one.
- **Schema preserved, no leakage.** `SELECT *` does not project the `rowid` pseudocolumn, so `fill_down`'s output
  columns are exactly the input columns (verified: preview columns unchanged) — `rowid` is never exposed to the
  client.
- **Single-table (ADR-006), single-writer (unchanged).** No new write path. `flag_outliers` compiles to the same
  `SELECT <cols>, expr AS new` add-column shape `calculated_column` ships; `fill_down` is an in-place column
  replace over the one table.
- **Bounded work.** Each op is one `CREATE TABLE … AS <select>` (apply) or read-only SELECTs (preview). The
  window functions (`LAST_VALUE`/`FIRST_VALUE`/`AVG`/`STDDEV_SAMP`) are full-frame analytics over the single
  table — bounded, no unbounded key space, no new external calls. The AI NL→SQL path and `GEMINI_API_KEY` are
  untouched.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean; Table bundle stays **ECharts-free**.
2. **#7a fill_down (down)** — carries the last non-null forward in row order; leading null with nothing to
   borrow stays null; row count unchanged; compiled SQL shows `LAST_VALUE … IGNORE NULLS OVER (ORDER BY rowid)`.
3. **#7a fill_down (up)** — carries the next non-null backward; trailing null stays null; compiled SQL shows
   `FIRST_VALUE … IGNORE NULLS`; unknown-column 400s.
4. **#7b flag_outliers** — adds a BOOLEAN column, true only for the true outlier; **exactly one** row flagged at
   threshold 3.0 on the fixture and **zero** at 10.0; compiled SQL shows `STDDEV_SAMP` + `ABS` over a full-frame
   window; text-column / name-collision / `threshold=0` each 400.
5. **Free plumbing proven** — preview shows 0 row-delta + compiled SQL for `fill_down` (and does **not** project
   `rowid`); **undo** after each op restores the prior state (fill_down restores the original nulls;
   flag_outliers removes the column); history logs the op.
6. Cache backend genuine: proof prints `REDIS BACKEND IN USE: redis` (v5.0.14.1 on :6380).
7. Must-not-change: **byte-clean** (`git diff` empty) for `duckdb_manager.py`, `sql_validator.py`, `README.md`;
   **no TASK-019 fingerprint** in `session.py` (transform routes byte-identical to HEAD), `.ai/CURRENT_STATE.md`,
   `api.ts`, `useSession.ts`, or `TableView.vue`.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (Redis on 6380, backend
`:8000`, Vite `:5173`); the frozen `duckdb_manager.py` and every must-not-change file free of any TASK-019
change; self-review with severity grades attached. **Sign-off is the user's — I do not self-close this task,
nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Verification (in-session, full stack live)
Stack: Redis `redis-server.exe` **v5.0.14.1** on **:6380**, backend `uvicorn --workers 1` on **:8000**
(`REDIS_PORT=6380`), Vite on **:5173**. The running backend holds the single-file `spencer.db` write lock, so
the in-process backend proof was run with the server stopped, then the server was restarted for the live browser
drive. A **W19 fixture** CSV was uploaded through the real UI: `id`, `region` (nulls at ids 1,3,5,12), `revenue`
(eleven 100s + one 200 at id 12). Each op was driven through the real `OpDialog`: open → fill via a Vue-aware
setter → read the preview → Apply → read the grid → Undo.

- **AC-1 — strict build:** fresh `vue-tsc -b && vite build` **clean, 0 TS errors** (final state, all edits in).
  The `>500 kB chunk` line is a **pre-existing advisory, not an error**. A grep of the three edited Table
  components (`OpDialog.vue`, `CleaningToolbar.vue`, `DataGrid.vue`) for `echarts|useEchart` returned **nothing**
  — the Table path stays ECharts-free.
- **AC-2 — fill_down down (live UI):** dialog `Fill down / up` with Column + Direction selects; preview
  **"12 → 12 rows (no row change)"**. After Apply the grid `region` = id1 `""` (leading null **stays null**),
  id3 `East` (from id2), id5 `West` (from id4), id12 `West` (from id11) — exactly the one leading null remains.
  Compiled SQL (backend proof): `SELECT * REPLACE (COALESCE("g", LAST_VALUE("g" IGNORE NULLS) OVER (ORDER BY
  rowid ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS "g")`.
- **AC-3 — fill_down up (backend proof):** compiled SQL `FIRST_VALUE("g" IGNORE NULLS) OVER (ORDER BY rowid ROWS
  BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)`; id1→'a' (next non-null), id3→'b', id5→'c', trailing id12 **stays
  null**. `fill_down` on an unknown column → `TransformError` "column 'nope' not found" (→ HTTP 400).
- **AC-4 — flag_outliers (live UI + backend proof):** dialog with Source column + New column name (preview gated
  by "Enter a new column name" until provided) + Method (zscore) + Threshold σ. On `revenue` / `rev_out` /
  threshold 3.0, preview **"12 → 12 rows (no row change)"**; after Apply the grid gained a **BOOLEAN** `rev_out`
  = `true` **only at id12 (200)**, `false` for all eleven 100s. Backend proof: compiled SQL
  `ABS("t0"."v" - AVG("t0"."v") OVER (…)) > (STDDEV_SAMP("t0"."v") OVER (…) * 3.0) AS "v_out"`; **exactly 1**
  flagged at 3.0, **0** at 10.0; guards — text column → "flag_outliers needs a numeric column; 'g' is VARCHAR",
  name collision → "column 'v' already exists", `threshold=0` → "requires a positive threshold" (each → 400).
  **Live guard:** flag_outliers on the text column `region` kept the dialog open with a VARCHAR error and the
  network trace showed `POST /transform → 400` **and** `POST /transform/preview → 400` (fail-closed, no 500);
  the console had only those two expected 400 resource errors, no JS/Vue runtime errors.
- **AC-5 — free plumbing:** preview for `fill_down` reported **0 row-delta**, exposed the compiled `LAST_VALUE`
  SQL, and its preview **columns stayed `[id, region, revenue]`** (rowid **not** projected) with the live table's
  null count unchanged; **Undo** on `flag_outliers` (live) removed `rev_out` and returned the grid to 3 columns
  while **leaving the earlier fill_down applied** (id12 region still `West`) — a correct step-by-step undo stack;
  the backend proof confirmed undo of `fill_down` restores all 4 original nulls, and `/history` logged the op
  (`['initial', 'fill_down']`). All from the op-agnostic pipeline with **no preview-specific code**.
- **AC-6 — cache backend genuine:** the backend test printed **`REDIS BACKEND IN USE: redis`**, server
  **5.0.14.1** on **:6380** (a fakeredis fallback would print `fakeredis`, voiding the proof per AP-9).
- **AC-7 — must-not-change:** **byte-clean (`git diff` empty):** `backend/services/duckdb_manager.py`,
  `backend/services/sql_validator.py`, `README.md`. **No TASK-019 fingerprint:** a grep for
  `fill_down|flag_outliers|FillDown|FlagOutliers` in `backend/routers/session.py`, `.ai/CURRENT_STATE.md`,
  `frontend/src/services/api.ts`, `frontend/src/composables/useSession.ts`, `frontend/src/views/TableView.vue`
  returned **nothing** (ops travel verbatim through `openOp`).
- **Backend test file:** `python test_transform_v2.py` — **RESULT: ALL CHECKS PASSED**, covering the new
  `task019_main` (fill down/up, flag_outliers, every guard, preview, history) and the new HTTP end-to-end cases
  (fill_down 200/12 rows; flag_outliers 200; threshold=0 → 400; text column → 400; preview exposes
  `STDDEV_SAMP`), alongside the pre-existing TASK-005/018 cases.
- **Screenshot — not captured (environment limitation).** `preview_screenshot` reported the Browser pane is not
  compositing frames (same limitation documented for TASK-016/017/018). All UI proof was gathered via
  `preview_snapshot` / DOM reads / the network trace (the authoritative text tools).

## Self-Review (severity-graded)
Grades: Critical / High / Medium / Low / Info. **No Critical, High, or Medium defects found.** `flag_outliers`
is one more instance of the reviewed add-a-transform pattern (typed model → one `_compile_structured` branch →
pure-presentation form). `fill_down` uses a distinct raw-SQL path, so it got extra scrutiny below — its single
interpolation point is a schema-validated, quoted identifier and its direction is a fixed template, so it carries
the same no-client-SQL guarantee (ADR-012) as the structured ops.

- **[Low] `fill_down` orders by `rowid`, i.e. current physical row order, not an arbitrary user key.** Fill
  direction follows the table's stored order (the same order `/data` shows). After an op that rewrites the table
  (e.g. a dedupe or a prior transform), `rowid` reflects the **post-transform** order, which is the order the
  user sees in the grid. **Why Low / intentional:** it matches the displayed order exactly, there is no
  user-facing "sort by" contract to violate, and a future enhancement could add an explicit order-by column if
  ordered-by-key fill is ever requested. No correctness or safety risk.
- **[Low] `flag_outliers` uses sample stddev (`STDDEV_SAMP`), so tiny-N columns can flag conservatively.** A lone
  outlier's max z-score is bounded by `(n-1)/√n`, so for very small N a real outlier can score below a high
  threshold (e.g. n=10 caps at 2.85 < 3.0). **Why Low / intentional:** this is correct sample-statistics
  behavior, the threshold is user-tunable, and it fails *safe* (under-flags rather than over-flags); documented
  here so the fixture's n=12 choice is understood.
- **[Low] `OpDialog` still allows Apply on an errored dry-run preview.** Carried over from TASK-016/017/018: if a
  preview 400s (e.g. flag_outliers on a text column), Apply stays clickable and simply fail-closes 400 again with
  no mutation (confirmed live — dialog stayed open, both requests 400, table unchanged). TASK-019 does not change
  this shared `OpDialog` trait. **Why Low:** it is fail-safe (no mutation) and a dialog property, not something
  these two ops introduce.
- **[Info] `fill_down` is the toolkit's only raw-SQL transform op — by necessity, and safely.** It cannot be an
  unbound-Ibis expression (no row identity there). The raw path interpolates exactly one value — a column name
  that must already exist in the live schema, quoted via `_quote_ident` — and picks between two fixed SQL
  templates by `direction`; no free-form user string reaches SQL. `SELECT *` preserves the schema (rowid not
  projected). This is the reason Wave 1 deferred it, resolved.
- **[Info] Both ops inherit preview / undo / redo / history for free.** `_compile_op` routes `fill_down` to its
  raw builder and everything else stays on `_compile_structured`; because apply/preview/undo/redo/history are
  op-agnostic, the new ops needed **no** pipeline change and got the full lifecycle (verified: preview 0-delta,
  undo restores prior state, history logs the op).
- **[Info] Additive, backward-compatible contract.** The two new models slot into the `op`-discriminated
  `TransformParam` union; `direction` defaults to `"down"`, `method` to `"zscore"`, `threshold` to `3.0`, so the
  additions cannot affect any existing client or payload.
- **[Info] `session.py` / `.ai/CURRENT_STATE.md` carry a parallel TASK-013 working-tree diff — NOT TASK-019.**
  Same note as TASK-018: `session.py`'s only diff hunks are its upload routes; its transform/undo/redo/preview
  routes are byte-identical to HEAD, and `CURRENT_STATE.md`'s diff is entirely TASK-013 documentation. Flagged
  only so the git state is not misread — TASK-019 touched neither.

## Status
IMPLEMENTATION COMPLETE — all 7 acceptance criteria proven live, self-reviewed (no Critical/High/Medium).
**SIGNED OFF 2026-08-23 (Wave 1b) → moved to `tasks/completed/`.** Downstream: Waves 2–7 per `tasks/BACKLOG.md`.
