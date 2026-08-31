# TASK-015

## Title
Column Profiler (Phase: Table data-prep) — click any column's ⋮ menu → **Profile column** opens a
side-panel with completeness (null %, distinct), and kind-appropriate detail: numeric → min/max/mean/
median/std + a fixed-bin histogram; temporal → min/max + most-frequent values; categorical/boolean →
most-frequent values. All numbers computed **server-side over the whole table** via Ibis→DuckDB SQL,
never a client-side reduction of the ≤1000-row grid window.

## Objective
First feature off the product backlog for the **Table** workspace. The grid already exposes a per-column
⋮ menu that funnels transform ops into `OpDialog`; profiling is a *read-only inspection*, not a transform,
so it gets its own menu entry, its own event, and its own panel — it never mutates data, bumps a version,
or writes a history step. On upload the user can immediately interrogate any column's shape (how complete
is it, how many distinct values, what's the spread) before deciding how to clean it.

## Context
Mirrors the Phase-5 `aggregate_service` exactly: only the column **name** travels from the client; it is
validated against the **live** schema (fresh `PRAGMA table_info` per request via the shared `_columns_of`,
never cached — a transform can add/drop/rename/retype a column); the actual SELECTs are built as **Ibis
expressions on an unbound table** and compiled to DuckDB SQL text (`ibis.to_sql(dialect="duckdb")`), then
run through the existing `db_manager.run_readwrite`. Ibis is a compiler here — it never opens its own
connection. At most **two** queries per profile: one scalar-stats row (always), plus one histogram
(numeric) or one top-N-values query (categorical/temporal/boolean).

The histogram's bin bounds are **server-computed floats** (from the column's own MIN/MAX), carried as
typed Ibis literals — they are never client input, so there is no user value on the `run_readwrite` path
(ADR-012). Single-table only (ADR-006) — the router resolves the table via `_resolve_table`.

## Requirements
1. **Backend model** — `ColumnProfile` (+ `ProfileHistogramBin`, `ProfileTopValue`) in `models/schemas.py`:
   `column`, `type` (raw DuckDB type), `kind` (`numeric|temporal|categorical|boolean`), `total`,
   `non_null`, `null_count`, `null_pct`, `distinct`, `min`/`max` (`Any` — ISO string for dates), numeric
   `mean`/`median`/`std` (`float|None`), `histogram` (bins), `top_values`, `compiled_sql`.
2. **Profile service** (`services/profile_service.py`, new) — mirrors `aggregate_service`: reuse
   `transform_service._unbound`/`_columns_of` and `aggregate_service._jsonable`; classify the column via
   Ibis dtype methods (`is_numeric`/`is_temporal`/`is_boolean`); **fail-closed** (unknown column →
   `ProfileError` → 400); one scalar `t.aggregate(...)`; numeric → fixed-bin (10) histogram with
   server-computed bounds (single-bin fast path when `min==max`, skipped when all-null); categorical/
   temporal/boolean → top-N (20) most-frequent non-null values; compile via `ibis.to_sql(duckdb)`; run via
   `db_manager.run_readwrite`; Decimal→float, date→ISO via `_jsonable`.
3. **Route** (`routers/query.py`) — `GET /{session_uuid}/profile/column?column=&table_name=` next to
   `get_data`; resolve the table with `_resolve_table` (404 if unknown, single-table); map `ProfileError`
   → HTTP 400. `column` is a required query param.
4. **Data layer** (`types.ts`, `api.ts`) — `ColumnProfile`/`ProfileHistogramBin`/`ProfileTopValue`/
   `ColumnProfileKind` types (snake_case to match FastAPI); `fetchColumnProfile(uuid, column, tableName?)`
   reusing the shared `http` client + `tableParam`.
5. **Panel** (`components/ColumnProfilePanel.vue`, new) — right-side drawer opened by a new
   `profile-column` event; fetches on open and re-fetches on `dataVersion`; renders completeness bar,
   numeric stat chips + CSS/SVG histogram, or top-value bars — **no ECharts** (Table bundle must stay
   ECharts-free); monotonic staleness guard + uuid guard; Escape to close; compiled SQL in `<details>`.
6. **Wiring** — `DataGrid.vue` adds a **Profile column** entry to the ⋮ menu emitting `profile-column:[col]`
   (separate from the transform `column-op` event); `TableView.vue` hosts the panel next to `OpDialog`.
7. **Strict build** — `vue-tsc -b && vite build` clean (string-literal unions, `import type`, no unused,
   relative imports).

## Files Expected To Change
- **Backend new:** `backend/services/profile_service.py`.
- **Backend edit:** `backend/models/schemas.py` (`ColumnProfile` + bin/top-value models),
  `backend/routers/query.py` (`/profile/column` route + import).
- **Frontend new:** `frontend/src/components/ColumnProfilePanel.vue`.
- **Frontend edit:** `frontend/src/services/api.ts` (`fetchColumnProfile`), `frontend/src/types.ts`
  (profile contract), `frontend/src/components/DataGrid.vue` (menu entry + event), `frontend/src/views/
  TableView.vue` (host the panel).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; only `run_readwrite` is called.
- **The `POST /chart` MessagePack stub** and the `/aggregate` route in `routers/query.py` — the new GET is
  added without touching them.
- **DataGrid's TASK-006 virtualizer / TASK-014 overscan** — the profiler adds a menu entry + emit only; the
  virtualizer config, scroll handling, and column logic are not on this path.
- **ADR-006 single-table / ADR-012 no client-assembled SQL** — upheld (see below).
- **`README.md` / `.ai/CURRENT_STATE.md`** — not touched; sign-off (and any roadmap update) is the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client-assembled SQL (ADR-012).** `fetchColumnProfile` sends the column as a typed query param;
  `profile_service.profile_column` validates it against the **live** schema (`_columns_of`) and then builds
  every SELECT with **Ibis** (`ibis.to_sql`). A client value can only ever be a column *identifier that
  already exists* — never interpolated SQL text. The histogram's `lo`/`width` literals are computed on the
  server from the column's own MIN/MAX, not from client input. `sql_validator.py` (which gates
  *AI-generated* SQL) is correctly not on this read-only structured path.
- **Fresh schema, never cached.** `profile_column` calls `_columns_of` (a `PRAGMA table_info`) on every
  request before building anything, so a column dropped/renamed/retyped by a transform is reflected
  immediately; a stale cached schema can't smuggle a now-invalid column into a compiled query.
- **Fail-closed → 400, never 500.** An unknown column raises `ProfileError`, mapped to HTTP 400. A bad
  request is a client error surfaced in the panel, not a server fault.
- **Single-table only (ADR-006).** The route resolves the target via `_resolve_table` → 404 if unknown; no
  join path introduced.
- **Bounded result size.** Histogram is a fixed 10 bins; top-values is clamped to 20. One request cannot
  return an unbounded key space.
- **No secrets, no new external calls.** Same-origin `:8000` API via the single Axios client; no API keys
  touched; the AI NL→SQL path is untouched.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean.
2. Profile a numeric column (e.g. `amount`) → `total`/`non_null`/`null_count`/`null_pct`/`distinct` and
   `min`/`max`/`mean`/`median`/`std` match hand-computed values over the FULL table; histogram bin counts
   sum to `non_null`.
3. Profile a categorical column with nulls (e.g. `rep`, which has empty cells) → `null_count`/`null_pct`
   correct; `top_values` are the most-frequent non-null values in DESC order, counts summing to `non_null`.
4. Profile a temporal column (`order_date`) → `min`/`max` are correct ISO dates; top values present.
5. Edge cases: a constant/single-distinct numeric column → single histogram bin (no divide-by-zero); an
   all-null column → no histogram/top values, stats zeroed, no crash; unknown column → friendly 400 in the
   panel.
6. After a Table-tab transform that drops the profiled column, the open panel refetches and shows a
   "column not found" 400 (honest); profiling a still-present column after a transform reflects new data.
7. `git diff -- backend/services/duckdb_manager.py` empty; `/chart` stub and `/aggregate` route unchanged;
   no ECharts import added to the Table path.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (Redis on 6380, backend
`:8000`, Vite `:5173`); the frozen `duckdb_manager.py`, the `/chart` stub, and the `/aggregate` route
unchanged; self-review with severity grades attached. **Sign-off is the user's — I do not self-close this
task, nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Verification (in-session, full stack live)
- **AC-1 — strict build:** `vue-tsc -b && vite build` clean, 0 TS errors.
- **Cache backend genuine:** proof printed `REDIS BACKEND IN USE: redis` (v5.0.14.1 on :6380); `schema:<uuid>`
  and `session:<uuid>` keys present on that instance (fakeredis would leave 6380 empty).
- **AC-2 — numeric (`amount`, 40 rows):** total 40 / non_null 40 / null 0 / distinct 40; min 95.5, max
  2450.75, mean 952.33725, median 710.0, std ≈702.6995. Histogram [9,7,6,4,1,2,3,3,4,1] sums to 40,
  width 235.525. **Independently recomputed from the raw CSV — exact match** (std differs by 1 ULP, expected
  float non-associativity between DuckDB `stddev_samp` and the manual recompute).
- **AC-3 — categorical w/ nulls (`rep`):** non_null 37 / null 3 / null_pct 7.5 / distinct 4; top values
  Alice 10, Bob 10, Dan 9, Carol 8 (sum 37, DESC, alphabetical tie-break Alice<Bob).
- **AC-4 — temporal (`order_date`):** kind temporal, min "2024-01-05", max "2024-03-31"; 20 top values;
  mean/median/std null (correct — not numeric).
- **AC-5 — edges:** `const_col` (single distinct) → one bin {x0:5.0,x1:5.0,count:4}, std 0.0, no
  divide-by-zero; `allnull_col` (VARCHAR) → non_null 0 / null_pct 100 / distinct 0, empty histogram + top,
  no crash; unknown column → HTTP 400 in the panel.
- **AC-6 — transform interaction:** dropped `category` (200) then profiled it → 400 "column 'category' not
  found" (honest); `region` still profiles fine (distinct 4).
- **AC-7 — must-not-change:** `git diff --stat -- backend/services/duckdb_manager.py` empty; `/chart` stub
  (`return b""`) and `/aggregate` route present/untouched; **no** `echarts`/`useEchart` import on the Table
  path (the only "ECharts" string is the ColumnProfilePanel comment asserting the bundle stays ECharts-free).

## Self-Review (severity-graded)
Grades: Critical / High / Medium / Low / Info. **No Critical, High, or Medium defects found.** The feature is
a small read-only endpoint that mirrors the already-reviewed `aggregate_service` and a self-contained,
ECharts-free panel. The notes below are deliberate design choices and honestly-surfaced edge properties.

- **[Low] TOCTOU between schema validation and the compiled SELECT.** `profile_column` issues `_columns_of`
  (validation) and then 1–2 separate `run_readwrite` SELECTs. A transform serialized in *between* those calls
  that dropped the column would make the compiled SELECT reference a missing column → a DuckDB error surfaced
  as 500 rather than the friendly 400. **Mitigation / why Low:** single-writer serialization prevents
  interleaving *within* a call; the single-user UI (ADR-006) can't fire a transform and a profile at the same
  instant, and the panel only refetches *after* dataVersion bumps. `aggregate_service` carries the identical
  pattern, so this is a pattern-level property, not a regression this task introduced. Not worth widening the
  frozen manager's surface to hold a lock across calls.
- **[Low] Read-only endpoint runs on `run_readwrite`.** A pure SELECT could use the rolled-back
  `run_sandboxed` path, but both share the one DuckDB connection so there is no concurrency difference;
  reusing `run_readwrite` matches `aggregate_service` exactly. Consistency chosen over a distinction without a
  difference. The frozen `duckdb_manager.py` was not touched.
- **[Info] Histogram right edge is closed on the last bin only.** Values map via
  `floor((v-lo)/width).clip(0, 9)`, so the maximum lands in bin 9; bins 0–8 are `[x0,x1)` and bin 9 is
  `[x0,x1]`. Standard histogram convention; the tooltip labels the last bin closed. Bin counts summed to
  `non_null` in every test, so no value is dropped or double-counted.
- **[Info] `std` is sample standard deviation** (Ibis `.std()` → DuckDB `stddev_samp`, n−1) — the
  conventional profiling choice; the independent recompute used the same definition and matched.
- **[Info] `distinct` excludes nulls** (`nunique()` → `COUNT(DISTINCT)` semantics): an all-null column reports
  distinct 0, verified. Consistent with "distinct non-null values."
- **[Info] Top-values truncation is surfaced, not hidden.** Categorical columns with >20 distinct values show
  the top 20 under a header reading "(of N distinct)", so the cap is visible to the user (no silent
  truncation). Tie-break is deterministic (`count DESC, value ASC`).
- **[Info] Staleness fully guarded on the client.** The panel uses a monotonic `seq` guard plus a
  `sessionUuid` guard so a late in-flight response can never overwrite a newer request (fast column-reopen or a
  mid-flight dataVersion bump); closing the panel invalidates any in-flight response.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **SIGNED OFF by user on 2026-08-29.**
