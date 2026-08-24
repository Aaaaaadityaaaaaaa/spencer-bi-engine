# TASK-022 — Wave 3: In-grid power (the Table's view-side toolkit)

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
Turn the server-paginated Table grid from a passive viewer into a working analysis surface —
**without breaking its virtualized, windowed contract** (the grid holds only a loaded prefix of the
table, never all rows). Five view-side powers, split by where the work has to happen:

| Feature | Where it must run | Why |
|---|---|---|
| **Multi-column sort** | **Server** | The grid has only a window; sorting the loaded prefix would lie. Sort feeds the `ORDER BY` of the windowed query so page 1 is the true top. |
| **Substring search** | **Server** | Same reason — filtering the prefix would miss matches further down. `q` feeds a bound `ILIKE` and `total` reflects the filtered count. |
| **Heatmap (colour scale)** | **Client, whole-table range** | The gradient needs the true column min/max, not the window's — so the server ships `ranges` once (offset 0), and the client paints. |
| **Pin / freeze column** | **Client** | Pure presentation (sticky-left); no data implication. |
| **Drag-reorder columns** | **Client** | Pure presentation (display order); no data implication. |

Sort and search are the two that would silently give **wrong answers** if done client-side on the
window — so they are the two pushed to the server. Heatmap/pin/reorder are presentation and stay local.
(Hide-column and Export shipped in earlier waves; the ⋮ menu now hosts all of them coherently.)

## The windowed-grid contract this wave had to respect
`DataGrid` is TanStack-virtualized with infinite scroll: `rows.value` is a growing **prefix** (concatenated
`PAGE=500` windows), `total` is the full row count, and `/data` uses `ORDER BY … NULLS LAST, rowid` for
stable non-overlapping windows. Everything below preserves that:
- Sort/search change the server `ORDER BY` / `WHERE`, then the grid **resets to the top** (`reloadFromTop`)
  and re-streams from offset 0 — never re-sorts a partial prefix.
- `ranges` (heatmap scale) arrives **only on the offset-0 window**, computed over the whole (unfiltered)
  column so the gradient is stable while you scroll or search.
- A **generation token** (`reqGen`) tags every window fetch; a reset bumps it, so a stale in-flight window
  (e.g. an old sort still resolving) is discarded instead of writing wrong rows — even when the session
  UUID is unchanged.

## What changed
### Backend
- **`backend/routers/query.py`** — `get_data` gains two optional query params:
  - `sort` — serialized `"col:dir,col:dir,…"`. `_parse_sort` splits it, validates **every column against the
    live `DESCRIBE` names** and the direction against `asc`/`desc`, and raises `400` on anything else
    (unknown column, bad direction, malformed pair). Compiles to `ORDER BY <quoted> [ASC|DESC] NULLS LAST, rowid`.
  - `q` — substring term. LIKE metacharacters (`%`, `_`, `\`) are escaped, then the term is **bound as a
    parameter** into an `ILIKE` `OR`-chain across every column `CAST … AS VARCHAR`. `total` is recomputed
    against the same filter so the row-count footer is truthful.
  - `ranges` — at **offset 0 only**, one aggregate `SELECT MIN(c), MAX(c)` over the numeric columns
    (`_is_numeric_type` / `_NUMERIC_PREFIXES`); returned as `{col: [min, max]}` for the client heatmap.
- **`backend/models/schemas.py`** — `DataResponse.ranges: Optional[Dict[str, List[float]]] = None` (additive;
  omitted ⇒ no heatmap data, unchanged clients unaffected).

### Frontend
- **`frontend/src/types.ts`** — `SortDir = 'asc' | 'desc'`, `SortSpec { column; dir }`, and
  `DataResponse.ranges?: Record<string, [number, number]>`.
- **`frontend/src/services/api.ts`** — `FetchDataParams` gains optional `sort?: SortSpec[]` and
  `search?: string`; `fetchData` serializes sort to `col:dir,…` and sends `q`, **omitting both when empty**
  so the default load is byte-identical to the pre-wave request (backward-compatible).
- **`frontend/src/components/DataGrid.vue`** — the view layer:
  - **Multi-sort:** header click cycles a single column `asc → desc → off`; **shift-click** is additive
    (numbered `1,2,…` badges show precedence). Each change `reloadFromTop()`s with the new `sortSpec`.
  - **Search:** debounced (300 ms) box → `search` → server `q`; empty-result state message; clear button.
  - **Heatmap:** per-column ⋮ toggle (numeric only). `heatBg(t)` interpolates **opaque** blue-50
    `[239,246,255]` → blue-600 `[37,99,235]` over the whole-table range; switches text to white at `t>0.62`
    for contrast. Opaque (not alpha) so a pinned+heatmap cell never shows scrolling content bleeding through.
  - **Pin/freeze:** ⋮ toggle → `position:sticky; left:<offset>` (pinned columns render first, each offset by
    `COL_W`); menu label flips Freeze ⇄ Unfreeze.
  - **Drag-reorder:** `draggable` headers reorder `colOrder` by name; pinned columns always lead.
  - **Reset view:** appears whenever any view state is non-default; clears sort/search/pin/heatmap/hide/order
    and refetches iff a server-affecting one (sort/search) was active.
  - **Race-safety:** `reqGen` generation token discards superseded windows; session switch resets **all** view
    state; a `dataVersion` bump (a transform) clears sort+search as a fail-safe (a renamed/dropped column would
    otherwise 400) but **keeps** pin/heatmap/order so a clean doesn't wipe your layout.

### Test
- **`backend/test_data_grid.py`** (new) — standalone, idempotent, **backend-stopped** (single-writer lock).
  22 assertions: default rowid order; `ranges` present for numeric / absent for text; single + multi sort;
  `NULLS LAST`; sort validation `400` (unknown column, bad direction); search filtering + filtered `total`;
  LIKE-escape; **injection inert** (a `q` of `%'; DROP …` is escaped + bound → 0 rows, no error); search+sort compose.

## Files that MUST NOT change (verified untouched)
`README.md`, `backend/services/duckdb_manager.py`, `backend/sql_validator.py` — confirmed absent from
`git diff`. `.ai/CURRENT_STATE.md` shows a diff, but that is the **parallel TASK-013 work pre-existing at
session start — not mine** (I edited none of it). `backend/routers/session.py`'s diff is likewise the
parallel TASK-013 change; query.py only *imports* `_resolve_table` / `_quote_ident` from it, no edit.

## Security (AP-8)
- **No client-assembled SQL (ADR-012).** Sort column names are validated against the **live `DESCRIBE`**
  before use and quoted via `_quote_ident`; an unknown or malformed column fails **closed (400)**, never
  reaches SQL. The search term never enters the SQL string — it is **escaped for LIKE metacharacters and
  bound as a parameter** to `ILIKE`.
- **Search is data, not code.** `q` is one bound parameter reused across the per-column `ILIKE` chain; a
  payload like `%'; DROP TABLE…` is treated as literal text (proven inert in `test_data_grid.py`, returns 0 rows).
- **Fail-closed → 400, never 500.** Bad sort column, bad direction, malformed `col:dir` pair → `_parse_sort`
  raises `400` with no query run. Read path only — no mutation, no version bump, no history.
- **Bounded work.** One windowed `SELECT` per page (`LIMIT/OFFSET`), plus a single `MIN/MAX` aggregate at
  offset 0 for `ranges`. Search widens the `WHERE` to an `OR`-chain over the (bounded) column set; no
  unbounded key space, no new external calls, no secrets touched.
- **Single-table (ADR-006), single-writer (unchanged).** No new write path introduced.

## Acceptance criteria (all proven live)
1. ✅ Strict `vue-tsc -b && vite build` clean (the >500 kB line is the known pre-existing ECharts-in-Canvas advisory).
2. ✅ **Backward-compatible:** the initial load sends **no** `sort`/`q` (request identical to pre-wave); response carries `ranges` for the 3 numeric columns only (`id[1,12]`, `revenue[120,3200]`, `units[3,80]`), VARCHAR columns excluded.
3. ✅ **Search:** `north` → `/data?…&q=north`, footer `3 / 3 rows (filtered)`, all rendered regions = North; clear restores full set.
4. ✅ **Sort cycle:** revenue header click → `sort=revenue:asc` (rows 120,150,450,540,610); again → `sort=revenue:desc` (3200,2750,2300,1750); third click → **cleared** (no `sort` param, rowid order, arrow gone).
5. ✅ **Multi-sort:** shift-click `product` then `units` → `sort=product:asc,units:asc`; badges render `product|1`, `units|2`; rows group by product then units within (Gadget/4,12,25,66 → Gizmo…).
6. ✅ **Heatmap:** ⋮ → Colour scale paints revenue min `120`→`rgb(239,246,255)`, max `3200`→`rgb(37,99,235)`, `1750`→`rgb(132,168,244)` (exact lerp of t=0.529), white text where t>0.62; VARCHAR `product` stays transparent.
7. ✅ **Pin/freeze:** freezing `units` moves it leftmost with `position:sticky; left:0px; z-index:5` (others `static`); menu label toggles to “Unfreeze column”.
8. ✅ **Drag-reorder:** dragging `region` onto `revenue` reorders `[units,id,region,product,revenue]`→`[…,product,revenue,region]`; pinned column stays first.
9. ✅ **Reset view:** clears order/heatmap/pin **and refetches** — after a sort, Reset returns rows to rowid order (`1,2,3,4,5`) with a fresh no-sort `/data` request (see self-review S-1: this AC caught a real bug).
10. ✅ **Guards:** sort with an unknown column / bad direction → `400`; injection `q` escaped + bound → 0 rows, no error (`test_data_grid.py`).
11. ✅ **Race-safety:** a superseded in-flight window is discarded via `reqGen` (stale sort cannot overwrite a newer reset).
12. ✅ Must-not-change diffs empty for `README.md`, `duckdb_manager.py`, `sql_validator.py`.

## Verification (real output)
- **`backend/test_data_grid.py`**: 22/22 assertions PASS, run with uvicorn stopped (single-writer lock).
- **Live full stack** (Redis :6380, uvicorn :8000 `--workers 1`, Vite :5173) against a 12-row fixture
  (`id/region/product/revenue/units`): every AC above driven through the running grid and confirmed via the
  live DOM, computed styles, and the `/data` request query strings (Performance API).
- Strict frontend build clean.

## Definition of Done
Five view-side powers implemented over the windowed-grid contract, self-reviewed with severity grades
(below), all ACs proven live + in-process. Left in `tasks/active/` for the user's single wave sign-off.
Not self-closed. `README.md` / `.ai/CURRENT_STATE.md` untouched.

## Self-review (severity-graded)
**Critical / High: none.**

- **S-1 (Medium — FOUND & FIXED, now resolved).** *Reset view left stale sorted rows.* `resetView()` set
  `sortSpec.value = []` **before** its own reload guard tested `sortSpec.value.length === 0` — so that
  condition was *always* true, and when a sort was active with **no** search (the common case), the guard
  short-circuited and **skipped the refetch**: sort indicators and the Reset button vanished while the grid
  still showed the old sorted rows — UI and data disagreed. The author had captured `hadSearch` before
  clearing search but forgot the equivalent for sort. Fix: capture `hadSort` (and `hadSearch`) **before**
  clearing, then `reloadFromTop()` iff either was set. Re-verified live: sort→rows `[2,5,10]`, Reset→rows
  `[1,2,3,4,5]` with a fresh no-sort `/data` request. Caught by AC-9 during live verification.
- **S-2 (Low — by design).** `ranges` (heatmap scale) is computed over the **whole, unfiltered** column and
  cached from the offset-0 window, so the gradient stays stable while you scroll or narrow with search — a
  cell keeps the same colour whether or not a search is active. Intended: the scale describes the column, not
  the current filter. It refreshes on the next `reloadFromTop` (sort/search/reset/transform).
- **S-3 (Low — by design).** Search is a substring `ILIKE` over **every column cast to VARCHAR**, so numeric
  matches hit the text rendering (searching `12` matches `revenue=1200` and `units=12`). This is the expected
  “find it anywhere” behaviour for a data grid; a typed/column-scoped filter is a separate future feature.
- **S-4 (Low — by design).** Sort/search are **cleared** on a `dataVersion` bump (a transform) as a fail-safe:
  a rename/drop could make an active sort column 400. Pin/heatmap/column-order are **kept** across transforms
  (they’re resilient to column changes via name-matching), so a clean doesn’t wipe your layout. Deliberate
  asymmetry, not an oversight.
- **S-5 (Low).** `NULLS LAST` is applied in **both** directions, so NULLs sink to the bottom on ascending and
  descending alike (NULL is treated as “no value”, not “smallest/largest”). A reasonable default; not
  user-configurable this wave.
- **S-6 (Info).** Multi-sort has no explicit cap on the number of sort columns — it is bounded by the column
  count and every column is validated, so this is safe; a very wide sort just yields a long (still valid)
  `ORDER BY`.
- **S-7 (Info).** Two live test-upload sessions remain in `spencer.db`; they expire via the normal session TTL
  sweeper. No manual cleanup needed.
