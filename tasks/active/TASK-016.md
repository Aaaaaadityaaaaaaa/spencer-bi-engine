# TASK-016

## Title
Data-quality panel (Phase: Table data-prep) — on upload and after every clean, a **collapsible card**
above the cleaning toolbar runs a battery of whole-table quality checks (>20% null, date/number stored as
text, mixed types, duplicate rows, constant columns, leading/trailing whitespace, empty columns) and shows
a **severity-ranked** list of findings. Each finding that maps to a cleaning op carries a one-click **Fix**
that opens the existing `OpDialog` pre-scoped to the offending column; the column name is a link into the
column profiler. All metrics are computed **server-side over the whole table** via Ibis→DuckDB SQL — never
a client-side reduction of the ≤1000-row grid window.

## Objective
Second feature off the **Table** data-prep backlog and the natural companion to the Column Profiler
(TASK-015): the profiler answers *"what does THIS column look like?"* on demand; the quality panel answers
*"what's wrong with the WHOLE table?"* automatically. It closes a satisfying loop — upload → see ranked
issues → click **Fix** → the finding is re-assessed and disappears. Like the profiler it is a **read-only
inspection**: it never mutates data, bumps a version, or writes a history step. The Fix action only routes
into the already-reviewed `OpDialog` (which dry-run previews before applying), so this feature adds **zero
new write paths**.

## Context
Mirrors the Phase-5 `aggregate_service` / TASK-015 `profile_service` exactly: every SELECT is built as an
**Ibis expression on an unbound table**, compiled to DuckDB SQL text (`ibis.to_sql(dialect="duckdb")`), and
run through the existing `db_manager.run_readwrite`. Ibis is a compiler here — it never opens its own
connection. **Crucially, no column input travels from the client at all**: the service enumerates columns
from the **live** schema itself (`transform_service._columns_of` — a fresh `PRAGMA table_info` per request,
never cached), so this path has even *less* client surface than the profiler. Single-table only (ADR-006) —
the router resolves the table via `_resolve_table`.

### Check battery (v1) and the Fix each maps to
Severity ranks `high > medium > low > info`; findings sorted by `(sev_rank, code, column)`. `suggested_op`
is an existing `OpKind`; `null` ⇒ informational (no Fix button). Thresholds are module constants
(`NULL_WARN=0.20`, `CAST_CONFIDENT=0.95`, `MIXED_LO=0.10`, `DUP_WARN=0.05`). `text_as_date` takes
precedence over `text_as_number` (a value parseable as both is flagged as the more specific date).

| Code | Trigger | Severity | suggested_op |
|---|---|---|---|
| `empty_column` | column 100% null | high | `drop_column` |
| `high_null` | 20% ≤ null% < 100% | medium | `impute_null` |
| `duplicate_rows` | exact-duplicate rows exist | medium (≥5% dup) / low | `dedupe` |
| `text_as_date` | string col, ≥95% of non-nulls `try_cast` to DATE | medium | `cast` |
| `text_as_number` | string col, ≥95% `try_cast` to number (and not already date) | medium | `cast` |
| `mixed_values` | string col, 10%–95% parse as number/date (inconsistent) | low | `null` (informational) |
| `whitespace` | string col, ≥1 value differs from its trimmed form | low | `string_normalize` |
| `constant` | non_null > 0 and distinct ≤ 1 | low | `drop_column` |

### Query strategy — bounded to ≤3 queries regardless of table width
- **Query A (all columns):** one `t.aggregate(**aggs)` with `total=t.count()` plus, per column *i*,
  `c{i}_nn=col.count()` (non-null) and `c{i}_nd=col.nunique()` (distinct) → drives null% + constant + empty.
- **Query B (string columns only; skipped if none):** one `t.aggregate(**aggs)` with, per string column *i*,
  `c{i}_num=col.try_cast('float64').count()`, `c{i}_dt=col.try_cast('date').count()`,
  `c{i}_ws=(col != col.strip()).sum()` → drives text-as-date/number, mixed, whitespace.
- **Query C:** `t.distinct().count()` → `duplicate_rows = total − distinct_rows`.

**Critical detail (differs from the profiler):** metric aliases are **server-generated, identifier-safe**
(`f"c{i}_nn"`, …), never the raw column name — so `t.aggregate(**aggs)` is safe even for a column named
`"2024"` or `"order id"`. Results are read back with `dict(zip(list(aggs.keys()), row[0]))` and mapped to
`columns[i]` by index. All ratios are guarded against divide-by-zero (computed only when the denominator > 0).

## Requirements
1. **Backend model** — `QualityFinding` + `QualityReport` in `models/schemas.py`: finding = `id`, `code`,
   `severity`, `title`, `detail`, `column` (nullable — table-level findings have none), `metric` (the number
   behind the finding), `suggested_op` (`OpKind|None`); report = `ok`, `row_count`, `column_count`,
   `findings`, `compiled_sql`.
2. **Quality service** (`services/quality_service.py`, new) — `class QualityError(Exception)` (→400);
   `assess_table(table_name)` returning a dict matching `QualityReport`. Reuses `transform_service._unbound`/
   `_columns_of` and `aggregate_service._jsonable`; classifies columns via Ibis dtype methods
   (`is_string`/`is_numeric`/`is_temporal`/`is_boolean`); the 3-query battery above; identifier-safe aliases;
   `compiled_sql = ";\n\n".join(sqls)` for transparency; **fail-closed** (unknown/empty table → `QualityError`).
3. **Route** (`routers/query.py`) — `GET /{session_uuid}/quality?table_name=` next to `/profile/column`;
   resolve via `_resolve_table` (404 if unknown, single-table); map `QualityError` → HTTP 400. **No column
   query param** — the service enumerates columns itself. `/chart` stub and `/aggregate` untouched.
4. **Data layer** (`types.ts`, `api.ts`) — `QualitySeverity`, `QualityCode`, `QualityFinding`,
   `QualityReport` (snake_case to match FastAPI; `suggested_op` reuses the `OpKind` union `| null`);
   `fetchQualityReport(uuid, tableName?)` reusing the shared `http` client + `tableParam`.
5. **Panel** (`components/DataQualityPanel.vue`, new) — a **collapsible card** (not a drawer — it is a
   whole-table overview). Header always carries a one-line status summary + per-severity count chips;
   default **expanded** when a high/medium finding exists (until the user manually toggles, after which
   their choice sticks across re-scans). Fetches on session set and **re-fetches on `dataVersion`** (so a
   Fix makes the finding vanish); monotonic `seq` guard + uuid guard. Each finding row: severity chip,
   title, detail, a Fix button (when `suggested_op`) emitting `fix:{op, column}`, and the column name as a
   link emitting `profile:column`. `ok` ⇒ compact green "No issues detected". Compiled SQL in `<details>`.
   **No ECharts** — the Table bundle must stay ECharts-free (CSS + Lucide icons only).
6. **Wiring** — `TableView.vue` mounts `<DataQualityPanel v-if="sessionUuid" @fix="openOp"
   @profile="openProfile" />` between `UploadDropzone` and `CleaningToolbar`. Both `openOp` and
   `openProfile` already existed (TASK-015) — **zero new handlers**, and the Fix reuses the existing
   `OpRequest {op, column?}`, so `OpDialog`/`CleaningToolbar`/`DataGrid` need no change.
7. **Strict build** — `vue-tsc -b && vite build` clean (string-literal unions, `import type`, no unused,
   relative imports).

## Files Expected To Change
- **Backend new:** `backend/services/quality_service.py`.
- **Backend edit:** `backend/models/schemas.py` (`QualityFinding` + `QualityReport`),
  `backend/routers/query.py` (`/quality` route + imports).
- **Frontend new:** `frontend/src/components/DataQualityPanel.vue`.
- **Frontend edit:** `frontend/src/services/api.ts` (`fetchQualityReport`), `frontend/src/types.ts`
  (quality contract), `frontend/src/views/TableView.vue` (mount the panel).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; only `run_readwrite` is called.
- **The `POST /chart` MessagePack stub** and the `/aggregate` route in `routers/query.py` — the new GET is
  added without touching them.
- **`OpDialog.vue` / `CleaningToolbar.vue` / `DataGrid.vue`** — the Fix path reuses the existing
  `OpRequest {op, column?}` + `TableView.openOp`; **no** new field on `OpRequest`, so these are untouched.
- **DataGrid's TASK-006 virtualizer / TASK-014 overscan** — not on this path.
- **ADR-006 single-table / ADR-012 no client-assembled SQL** — upheld (see below).
- **`README.md` / `.ai/CURRENT_STATE.md`** — not touched; sign-off (and any roadmap update) is the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client-assembled SQL (ADR-012).** `/quality` takes only `table_name`; there is **no column input from
  the client at all**. `assess_table` enumerates columns from the **live** schema (`_columns_of`, a fresh
  `PRAGMA table_info` per request, never cached) and builds every SELECT with **Ibis** (`ibis.to_sql`). The
  `try_cast` target types (`float64`/`date`) are **server constants**. Metric aliases are server-generated
  (`c{i}_*`), never client text. `sql_validator.py` (which gates *AI-generated* SQL) is correctly not on this
  read-only structured path.
- **Fresh schema, never cached.** Because `_columns_of` runs per request, a column dropped/renamed/retyped by
  a transform is reflected on the very next scan; a stale cached schema can't smuggle a now-invalid column
  into a compiled query.
- **Fail-closed → 400/404, never 500.** Unknown/empty table → `QualityError` → HTTP 400; unknown table via
  `_resolve_table` → 404. Verified: 0 tracebacks/500s in the backend log across the whole verification run.
- **Single-table only (ADR-006).** Resolved via `_resolve_table` → 404 if unknown; no join path introduced.
- **Bounded work.** ≤3 queries regardless of column count; findings naturally bounded (≤~2/column + 1
  table-level) and severity-sorted. One request cannot return an unbounded key space.
- **No secrets, no new external calls.** Same-origin `:8000` API via the single Axios client; no API keys
  touched; the AI NL→SQL path is untouched.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean.
2. Upload a CSV with known issues (>20%-null column, date-as-text, number-as-text, duplicate rows, constant
   column, whitespace column, all-null column) → each surfaces with correct severity, correct `metric`, and
   the mapped `suggested_op`; counts/percentages match hand-computed values over the FULL table.
3. Click **Fix** on a finding → `OpDialog` opens pre-scoped to that column/op; applying bumps `dataVersion`,
   the panel re-assesses, and the resolved finding disappears; the re-scan is a genuine whole-table recompute.
4. Clean table (no issues) → green "No issues detected" state; `ok:true`, empty findings.
5. Edge cases: empty table (0 rows) → no crash, no divide-by-zero; all-null column → single `empty_column`
   (not `high_null`); a column named `"2024"`/with a space → checks still run (identifier-safe aliases);
   unknown table / bogus session → 400/404 in the panel, not a 500.
6. Cache backend genuine: proof prints `REDIS BACKEND IN USE: redis` (v5.0.14.1 on :6380).
7. Must-not-change: `git diff -- backend/services/duckdb_manager.py` empty; `/chart` stub + `/aggregate`
   unchanged; `OpDialog.vue`/`CleaningToolbar.vue`/`DataGrid.vue` untouched by this task; no ECharts import
   on the Table path.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (Redis on 6380, backend
`:8000`, Vite `:5173`); the frozen `duckdb_manager.py`, the `/chart` stub, and the `/aggregate` route
unchanged; self-review with severity grades attached. **Sign-off is the user's — I do not self-close this
task, nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Verification (in-session, full stack live)
Test fixture: a deterministic 22-row / 8-column CSV (`id, region, blank, pct, amount_txt, when_txt, messy,
city`) built to exercise all 8 checks at once, with expected metrics **independently recomputed** by an
in-memory DuckDB (raw SQL, not the service) as ground truth. `amount_txt` and `when_txt` each carry one
`"N/A"` sentinel so they stay VARCHAR (95.45% parse ratio, just over the 95% threshold). Two exact duplicates
of row 1 give `duplicate_rows = 2`.

- **AC-1 — strict build:** `vue-tsc -b && vite build` clean, 0 TS errors (after adding `QualityReport` to the
  `api.ts` import block — the one build failure, fixed).
- **Cache backend genuine (AC-6):** fresh `python -c "…redis_manager.backend"` with `REDIS_PORT=6380` printed
  backend `redis`, server **5.0.14.1** on :6380 (fakeredis fallback would print `fakeredis`).
- **AC-2 — findings match hand-computed (22 rows):** header **"1 high · 4 medium · 3 low · 8 issues across 8
  columns · 22 rows"**, findings exactly:
  - `empty_column` **blank** (high, `drop_column`) — 100% null.
  - `high_null` **pct** (medium, `impute_null`) — 5 nulls / 22 = **22.73%**.
  - `text_as_date` **when_txt** (medium, `cast`) — 21/22 date-parseable = **95.45%** (precedence over number).
  - `text_as_number` **amount_txt** (medium, `cast`) — 21/22 numeric-parseable = **95.45%**.
  - `duplicate_rows` (medium, `dedupe`) — 2 dup rows = 9.09% (≥5% ⇒ medium).
  - `constant` **region** (low, `drop_column`) — distinct 1 ("West").
  - `mixed_values` **messy** (low, informational) — 12/22 ≈ 54.5% numeric (between 10% and 95%).
  - `whitespace` **city** (low, `string_normalize`) — "Alice "/" Bob" differ from trimmed.
  - `id` correctly clean (no finding). All numbers matched the independent DuckDB recompute.
- **AC-3 — Fix → re-assess loop:** clicked **Fix** on `duplicate_rows` → `OpDialog` opened on `dedupe` →
  dry-run preview 22→20 → applied → `dataVersion` bumped → panel re-scanned. `duplicate_rows` finding
  **disappeared**, header became **"1 high · 3 medium · 3 low · 7 issues … · 20 rows"**, and **pct's null%
  recomputed 22.73% → 25.0%** — proving the re-scan is a genuine whole-table recompute, not a cached report.
  Also exercised the `cast` Fix on `when_txt`: it opened `OpDialog` correctly scoped to that column, but a
  strict cast to DATE was **rejected 400 (fail-closed, no mutation)** by the "N/A" sentinel — see the Low
  note below.
- **AC-4 — clean table:** a no-issue CSV → panel showed the green "No issues detected" state; `ok:true`,
  empty findings.
- **AC-5 — edges:** `blank` (100% null) surfaced as **`empty_column`, not `high_null`** (proves the guard);
  clean-CSV columns named `"2024"` and with a space still scanned (identifier-safe aliases); empty/0-row
  table returned with no divide-by-zero; **unknown table → 404**, **bogus (all-zeros) session → 404**, both
  surfaced in the panel, never a 500.
- **AC-7 — must-not-change:** `git diff --stat` on `duckdb_manager.py`, `OpDialog.vue`, `CleaningToolbar.vue`
  = **empty**. `query.py`: TASK-016 added only the `/quality` route block; the `/chart` `build_chart` stub is
  present and unchanged (the diff also shows `/aggregate` + `/profile/column` as prior uncommitted additions
  from TASK-011/015 — not modified here). `DataGrid.vue` shows a diff but it is **pre-existing** uncommitted
  work (` M` at session start; the new panel is `??`), and it has **0** references to
  `quality`/`DataQualityPanel`/`assess_table`/`fetchQualityReport` — TASK-016 did not touch it. **No** ECharts
  import on the Table path: the only "ECharts" string in `DataQualityPanel.vue` is the line-8 comment
  asserting the bundle stays ECharts-free.
- **Screenshot — not captured (environment limitation).** `preview_screenshot` timed out repeatedly ("Browser
  pane is not displayed, so the page is not compositing frames"), unrelated to code or server health.
  Structural/text proof was gathered throughout via `preview_snapshot` (the authoritative text tool per the
  preview tooling), which confirmed the header summary, findings list, Fix buttons, and column links live.

## Self-Review (severity-graded)
Grades: Critical / High / Medium / Low / Info. **No Critical, High, or Medium defects found.** The feature is
a small read-only endpoint that mirrors the already-reviewed `aggregate_service`/`profile_service` and a
self-contained, ECharts-free card whose only side effect is emitting an `OpRequest` into the existing,
already-reviewed `OpDialog`. The notes below are deliberate design choices and honestly-surfaced properties.

- **[Low] A `cast` Fix on `text_as_date`/`text_as_number` opens the right tool, but a *strict* cast fails on
  the very sentinel that triggers the finding.** A column stays VARCHAR (and thus gets flagged) precisely
  because a non-parseable token like "N/A" keeps its parse ratio at ~95%, not 100%. The Fix opens `OpDialog`
  correctly scoped to that column with `cast`, but a strict `CAST … AS DATE/DOUBLE` then fails (fail-closed
  400, **no mutation**) on that sentinel; the user must first null the sentinel (`string_normalize`
  null_token) and then cast — a known **two-step**. **Why Low:** behavior is honest and safe (dry-run preview
  + fail-closed apply both protect the data; the finding correctly persists until genuinely resolved). Not a
  defect in TASK-016 code — it is the interaction between an honest finding and `OpDialog`'s strict cast. A
  future enhancement could offer a coercing/`try_cast` option in the cast dialog.
- **[Low] TOCTOU between column enumeration and the compiled SELECTs.** `assess_table` calls `_columns_of`
  (validation) and then runs ≤3 separate `run_readwrite` SELECTs. A transform serialized *between* those
  calls that dropped a column would make a compiled SELECT reference a missing column → a DuckDB error
  surfaced as 500 rather than 400. **Mitigation / why Low:** single-writer serialization prevents interleaving
  *within* a call; the single-user UI (ADR-006) cannot fire a transform and a scan at the same instant, and
  the panel only refetches *after* `dataVersion` bumps. `aggregate_service`/`profile_service` carry the
  identical pattern — a pattern-level property, not a regression this task introduced. Not worth widening the
  frozen manager's surface to hold a lock across calls.
- **[Low] `OpDialog` allows submitting Apply on an errored dry-run preview.** Observed during AC-3: the
  `when_txt`→DATE cast preview returned 400, yet Apply was still clickable (two apply attempts, both
  fail-closed 400 at the backend with **no mutation**). The backend fail-closed guarantee protected the data.
  This is an `OpDialog` (must-not-change) trait, **out of TASK-016's scope**, surfaced honestly; my panel only
  ever *emits* an `OpRequest` and never touches a write path. A future `OpDialog` task could disable Apply
  while the preview is in an error state.
- **[Info] `.try_cast()` availability confirmed (Step 0).** `ibis.literal("x").try_cast("date")` compiles in
  this repo's Ibis, so the raw-`TRY_CAST` fallback in the plan was not needed; `try_cast` target types remain
  server constants either way.
- **[Info] Identifier-safe metric aliases (the key difference from the profiler).** Aggregate aliases are
  server-generated `c{i}_nn`/`c{i}_nd`/`c{i}_num`/`c{i}_dt`/`c{i}_ws`, never raw column names, and results are
  mapped back to `columns[i]` by index — so `t.aggregate(**aggs)` is safe for a column named `"2024"` or
  `"order id"`. Verified live on a clean CSV with such columns.
- **[Info] `text_as_date` precedence over `text_as_number`.** A value parseable as both is flagged as the
  more specific date; the number check is skipped for a column once its date ratio clears `CAST_CONFIDENT`.
- **[Info] `duplicate_rows` severity is threshold-based.** ≥5% duplication ⇒ medium, else low (`DUP_WARN`);
  the fixture's 9.09% → medium. A handful of dups in a very large table is intentionally the milder low.
- **[Info] Divide-by-zero fully guarded.** Ratios are computed only when their denominator > 0; an empty
  table does no per-column ratio work, and an all-null column short-circuits to `empty_column` before any
  null%/parse ratio. Verified via `blank` (→ `empty_column`, never `high_null`) and the 0-row table.
- **[Info] `distinct` excludes nulls** (`nunique()` → `COUNT(DISTINCT)` semantics), consistent with the
  profiler; `constant` therefore fires only when `non_null > 0 and distinct ≤ 1`.
- **[Info] Read-only endpoint runs on `run_readwrite`.** A pure SELECT could use the rolled-back sandbox path,
  but both share the one DuckDB connection so there is no concurrency difference; reusing `run_readwrite`
  matches `aggregate_service`/`profile_service` exactly. The frozen `duckdb_manager.py` was not touched.
- **[Info] Staleness fully guarded on the client.** The panel uses a monotonic `seq` guard plus a
  `sessionUuid` guard, so a late in-flight response can never overwrite a newer one (fast re-scan or a
  mid-flight `dataVersion` bump); a session change invalidates any in-flight response and resets the
  manual-toggle memory.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
