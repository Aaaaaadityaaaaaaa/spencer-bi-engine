# TASK-021 — Data-quality scanner: catch all six issue classes

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
Extend the whole-table data-quality scanner (`quality_service.assess_table`, TASK-016) so it
detects **all six** data-quality issue classes the user named, not just the three it already
covered. Independent of the pending Wave 2 / TASK-020 sign-off.

| Issue class (user's words) | Example | Before | Now |
|---|---|---|---|
| Missing data — NULL, N/A, blanks | blank / "N/A" / "-" | 🟡 real NULLs only (`high_null`) | ✅ + **`hidden_null`** (placeholder tokens) |
| Duplicates — same transaction twice | identical rows | ✅ `duplicate_rows` | ✅ (unchanged) |
| Wrong format — `23/08/26` vs `2026-08-23` | mixed date layouts | ⬜ | ✅ **`mixed_date_format`** |
| Wrong data type — `"25"` instead of `25` | number/date stored as text | ✅ `text_as_number` / `text_as_date` | ✅ (unchanged) |
| Invalid values — `Age = -10` | negatives / future dates | ⬜ | ✅ **`negative_values`** + **`future_date`** (review-only) |
| Inconsistent categories — `Male, M, male` | casing variants | ⬜ | ✅ **`inconsistent_case`** |

Five new finding codes: `hidden_null`, `inconsistent_case`, `mixed_date_format`,
`negative_values`, `future_date`.

## How the scan "reads all the rows" (the mechanism the user asked about)
It never streams rows into Python. Every check is a **column aggregate** — `COUNT`, `SUM(CAST(… AS INT))`,
`COUNT(DISTINCT …)` — compiled from an **unbound Ibis expression** to DuckDB SQL and run inside DuckDB
over the whole table. DuckDB scans the column once and returns a single number per check. The scan stays
bounded to **at most 4 queries regardless of table width** (a column named `"2024"` or `"order id"` is
safe: per-column metrics use server-generated aliases `c{i}_…`, never the raw name):

- **Query A** — over *all* columns: total rows, per-column non-null count + distinct count → empty / constant / high-null.
- **Query B** — over *string* columns only: TRY_CAST-to-number/date, whitespace, **hidden-null sentinels**, **case-folded distinct**, **date-shape regex counts**.
- **Query C** — one scalar: distinct full-row count → duplicate rows.
- **Query D** — over *numeric + date/timestamp* columns: **negative count**, **after-now count**.

## What changed
### Backend
- **`backend/services/quality_service.py`**
  - New constants: `SENTINELS` (null-token list: `N/A, NA, NULL, NONE, NIL, -, ?, --, ., (BLANK)`),
    `CATEGORICAL_MAX=50`, `DATE_SHAPE_MIN=0.10`, `DATEISH_MIN=0.60`, two date-shape regexes (ISO-dash, slash).
  - **Query B** gains four per-string-column aggregates: `_hn` (blank-after-trim OR sentinel, case-insensitive),
    `_fd` (`COUNT(DISTINCT LOWER(TRIM(col)))`), `_iso` / `_sl` (date-shape match counts).
  - **New Query D** over numeric + temporal columns: `SUM(col < 0)` and `SUM(col > CURRENT_DATE / CURRENT_TIMESTAMP)`
    (via `ibis.today()` / `ibis.now()`, chosen by column type). Skipped when the table has no such columns.
  - New findings derived:
    - `hidden_null` (medium, → `string_normalize`) — placeholder tokens that read as present but mean missing.
    - `inconsistent_case` (medium, → `string_normalize`) — low-cardinality column whose distinct count shrinks once case/space is folded; skipped for numeric/date-ish columns.
    - `mixed_date_format` (low, **review-only**) — ≥2 date layouts each ≥10% of non-nulls and ≥60% date-shaped overall. **Checked before `text_as_date`** (see self-review S-1).
    - `negative_values` / `future_date` (low, **review-only** — `suggested_op=None`, no Fix button) — so a legitimate negative or future date is never destroyed by a one-click fix.
- **`backend/models/schemas.py`** — extend the `QualityFinding.code` `Literal` with the five new codes (additive; existing codes unchanged).

### Frontend
- **`frontend/src/types.ts`** — add the five codes to the `QualityCode` union (mirrors the wire).
- **`frontend/src/components/DataQualityPanel.vue`** — the panel already renders findings generically
  (title/detail/severity chip; Fix button iff `suggested_op`). Only change: broadened the `string_normalize`
  op label from "Trim text" → "Normalize text" (now that `hidden_null`/`inconsistent_case` also route there).
  The three review-only codes render with no Fix button automatically.

### Test
- **`backend/test_quality.py`** (new) — standalone, idempotent, backend-stopped proof over a typed fixture
  engineered to trip each new check exactly once (+ a duplicate row for regression). 22/22 assertions.

## Files that MUST NOT change (verified untouched)
`README.md`, `.ai/CURRENT_STATE.md` (the diff there is the parallel TASK-013 work, pre-existing at session
start — not mine), `backend/services/duckdb_manager.py`, `backend/sql_validator.py`. Confirmed absent from
`git diff`.

## Security (AP-8)
- **No client-assembled SQL (ADR-012).** Column names come from the LIVE schema (`_columns_of`, fresh PRAGMA),
  never from the client. The scan takes no column input at all. Sentinels / regex patterns / horizons are
  **Ibis literal arguments** (parameterized), never string-concatenated into SQL.
- **Regex is data, not code.** The two date-shape patterns are fixed module constants passed as literals to
  `REGEXP_MATCHES`; they evaluate over column data and cannot introduce SQL.
- **Read-only.** The scan issues only SELECT aggregates through `db_manager.run_readwrite`; it never mutates,
  bumps a version, or writes history. Fixes route through the existing `OpDialog` dry-run path unchanged.
- **Review-only = data-safe.** `negative_values` / `future_date` / `mixed_date_format` carry `suggested_op=None`,
  so the UI shows no one-click fix — a legitimate negative, future date, or ambiguous date layout cannot be
  silently destroyed.
- **Bounded work.** Still ≤4 aggregate queries over one table regardless of width; no new external calls,
  no secrets touched.

## Acceptance criteria (all proven)
1. ✅ Strict `vue-tsc -b && vite build` clean (the >500 kB line is the known pre-existing advisory).
2. ✅ `hidden_null` counts blanks + sentinel tokens (metric 3 on the typed fixture; 2 live where DuckDB read the empty CSV field as a real NULL — correct).
3. ✅ `inconsistent_case` fires on `Male/male/M/Female/female/F` (6 distinct → 4 folded, metric 2); not on already-typed columns.
4. ✅ `mixed_date_format` fires on a text column mixing ISO + slash (metric 83.33% live); **outranks `text_as_date`** so a mixed column isn't offered a corrupting cast.
5. ✅ `negative_values` counts `-10, -5` (metric 2); does not flag the clean positive `id` column.
6. ✅ `future_date` counts dates after today (metric 2); via `CURRENT_DATE` for DATE, `CURRENT_TIMESTAMP` for TIMESTAMP.
7. ✅ Review-only codes have no Fix button; `hidden_null`/`inconsistent_case` route to `string_normalize`.
8. ✅ Pre-existing checks (duplicate/empty/constant/high-null/text-as-*/whitespace/mixed) unchanged; `test_export.py` still 22/22 (shared `schemas.py` edit is additive).
9. ✅ Scan stays ≤4 queries; cache backend genuine (`REDIS BACKEND IN USE: redis`, v5.0.14.1 on :6380).

## Verification (real output)
- **`backend/test_quality.py`**: `RESULT: ALL CHECKS PASSED` (22/22), `REDIS BACKEND IN USE: redis (v5.0.14.1)`, run with uvicorn stopped.
- **`backend/test_export.py`**: `RESULT: ALL CHECKS PASSED` — no regression from the shared `schemas.py` edit.
- **Live HTTP** (uvicorn on :8000, real ingestion path): CSV upload → `GET /quality` returned
  `hidden_null:status`, `inconsistent_case:gender`, `negative_values:age`, `future_date:event_date`, `duplicate_rows`;
  a second upload (date column kept VARCHAR) returned `mixed_date_format:dt` (83.33%, review-only).
- Strict frontend build clean; ibis type-predicates (`is_numeric/is_boolean/is_date/is_timestamp`) confirmed in 12.0.0.

## Definition of Done
Five new checks implemented, self-reviewed with severity grades (below), all ACs proven live and in-process.
Left in `tasks/active/` for the user's single sign-off. Not self-closed. `README.md` / `.ai/CURRENT_STATE.md` untouched.

## Self-review (severity-graded)
**Critical / High / Medium: none.**

- **S-1 (Medium — FOUND & FIXED, now resolved).** First test run flagged the format-mixed `joined` column as
  `text_as_date` (metric 100%), *not* `mixed_date_format`: DuckDB 1.5.5's `TRY_CAST(AS DATE)` parses **both**
  `2026-01-05` and `05/01/26`, so a mixed column looked fully castable — and the suggested cast would silently
  guess DMY-vs-MDY and corrupt data. Fix: `mixed_date_format` is now checked **before** `text_as_date` in the
  elif chain, so a column with ≥2 date layouts is flagged review-only instead of offered a corrupting cast.
  Regression-locked by the `'joined' is mixed_date_format, NOT text_as_date` assertion.
- **S-2 (Low — by design).** Post-ingest, DuckDB's CSV type-inference may auto-parse a mixed-format date column
  straight to TIMESTAMP (observed live), resolving — or silently mis-resolving — the format mix *before* the scan
  sees it. `mixed_date_format` therefore fires only while such dates remain **text** (VARCHAR), which is the case
  the check targets. Documented, not a defect: the scan inspects the table as stored.
- **S-3 (Low).** `SENTINELS` is a fixed English/′symbol list (`N/A`, `-`, `?`, `.`, `(BLANK)`, …). A domain-specific
  token (e.g. `TBD`, `9999`) won't be caught. Extending the constant is a one-line change; kept conservative to
  avoid flagging legitimate values like a lone `-` that means something in-domain.
- **S-4 (Low).** `inconsistent_case` only scans columns with ≤50 distinct values (categorical). A high-cardinality
  free-text column with casing noise is intentionally skipped (casing there is rarely a category-merge problem and
  would be noisy). Threshold is a tunable constant.
- **S-5 (Info).** `hidden_null` / `inconsistent_case` route their Fix to the generic `string_normalize` dialog
  (opened scoped to the column) rather than pre-seeding the exact sub-operation (null-token replace / lowercase).
  The dialog's dry-run preview is the safety gate; pre-seeding is a future nicety, deliberately out of scope.
- **S-6 (Info).** Two live test-upload sessions remain in `spencer.db`; they expire via the normal session TTL
  sweeper (same as any upload). No manual cleanup needed.
