# TASK-041 — Data-grid / quality / chart feedback batch (10 fixes)

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (in `tasks/active/`; not self-closed)

## Objective
A single batch closing ten pieces of feedback, built to touch the fewest surfaces per fix:

1. **Chart Y-axis numbers hidden until enlarged** — value-axis tick numbers now show at any tile size.
2. **One-tap fixes for two data-quality issues** — `order_date` mixed/inconsistent values and `quantity`
   negatives now carry a pre-filled Fix (coercing cast / keep ≥ 0).
3. **Merge `upi` / `u.p.i`** — a "collapse spacing + drop punctuation" normalize folds separator variants of one
   category together.
4. **Fill nulls with mean/median + decimal-places** — an optional "round to N decimals" on a computed fill.
5. **In-cell editing** — double-click any grid cell to edit it; persisted as a real, undoable transform.
6. **Stronger data-quality detection** — sub-threshold missing values + punctuation/spacing category variants.
7. **Ignore option in Data Quality** — dismiss an issue (and restore it) without fixing it.
8. **Bug: sibling warnings vanish** — fixing a column's type no longer drops its unrelated missing-values warning.
9. **Column ⋮ menu not scrollable** — the per-column header menu now scrolls when it's taller than the viewport.
10. **Friendly table name** — the internal `t_<uuid>_…messy_sales_dataset_100k` reads as `messy_sales_dataset_100k`.

## Approach & why

### Backend — detection, one-tap seeds, and two op extensions (all Ibis-compiled / rowid-SQL, ADR-012)
- **#6 / #8 stronger, type-agnostic detection** (`quality_service.assess_table`):
  - **`partial_null`** — sub-threshold missingness (any `null_count > 0` below the high-null bar) is now emitted on
    the **null axis for every column regardless of type**, not inside the string-only branch. That is the #8 fix:
    casting a "stored as text" column to a number used to move it out of the string branch and silently drop its
    missing-values finding; now the missing-value signal is independent of type and **survives the cast**.
  - **`inconsistent_values`** — a new *canonical-distinct* metric (`lower → drop punctuation → collapse
    whitespace → nunique`) fires when values collapse further than case-folding alone, i.e. the same category
    written with different separators (`upi` / `u.p.i` / `U P I`). The metric is computed with **exactly** the
    normalize the one-tap Fix applies, so a flagged column genuinely merges when fixed (#3/#6).
- **#2 one-tap Fixes via `suggested_params`** — `QualityFinding` gained an optional `suggested_params` bundle that
  pre-fills the Fix dialog. `mixed_values` now suggests a **coercing cast** to the dominant parsed type
  (`{coerce, new_type: DATE|DOUBLE}`); `negative_values` suggests **keep ≥ 0** (`filter_rows` with the quoted
  column predicate); `inconsistent_values` / `inconsistent_case` suggest the matching **normalize**. The scan
  stays read-only — the fix still runs through the dialog's dry-run Review Gate before anything mutates.
- **#4 impute decimals** — `TransformImputeNull.decimals` (0–10) rounds a computed `mean`/`median` via Ibis
  `.round(n)` (ignored for zero/mode/custom, which aren't long decimals).
- **#3 collapse whitespace** — `TransformStringNormalize.collapse_whitespace` collapses internal whitespace runs
  to one space and trims the ends (after `strip_special`), so `" u . p . i "` folds to `upi`.
- **#5 in-cell edit** — `TransformUpdateCell {column, rowid, value}` sets one cell addressed by its stable DuckDB
  `rowid` (the same anchor `/data` pages by). Like `fill_down` it compiles **raw rowid SQL** (`SELECT * REPLACE
  (CASE WHEN rowid = ? THEN <lit> ELSE col END AS col) … ORDER BY rowid`) because an unbound Ibis table has no
  row identity. **Security:** `column` is validated against the live schema then quoted, `rowid` is int-coerced
  (≥ 0), and the value is a doubled-quote literal wrapped in a strict `CAST` to the column's *own* PRAGMA-derived
  type — a value that can't parse **fails closed as a 400**, never as raw SQL text. `value: null` clears to NULL.
  `/data` now returns a **`rowids`** array parallel to `rows` so the grid can target an exact cell under any
  sort/search.

### Frontend — dialog seed-mapping, optimistic cell edit, ignore state, and two display-only tweaks
- **#2/#3/#4/#6 seed mapping** — the quality panel's Fix passes a finding's `suggested_params` through as an
  `OpRequest.seed`; `OpDialog.applySeed()` maps the **snake_case op-field keys** (`coerce` / `new_type` /
  `predicate` / `action` / `case` / `trim` / `strip_special` / `collapse_whitespace` / `strategy` / `decimals` /
  `fill_value`) onto its form, **type-checked key-by-key** and applied *after* the per-op defaults so a Fix opens
  the dialog one Apply away. New form controls: the impute "round to N decimals" checkbox+input (#4) and the
  normalize "collapse repeated spaces" checkbox (#3).
- **#5 in-cell edit** — a dedicated `useSession.updateCell()` persists the single cell (undoable, snapshotted)
  **without bumping `dataVersion`** — a normal transform bump clears the grid's sort/search and scrolls to top,
  which would yank the user off the cell they just edited. Instead `DataGrid` patches the one cell optimistically
  and rolls back on failure. Double-click a cell → inline `<input>` (Enter commits, Esc cancels, blur commits).
- **#7 Ignore** — per-session, `localStorage`-persisted set of dismissed finding ids (ids are stable
  `"{code}:{column}"`, so a dismissal sticks across re-scans and only a genuinely new issue resurfaces).
  `activeFindings` drives the list + header counts + auto-expand; a collapsible "N ignored" section lists
  dismissed findings with a Restore button.
- **#9 scrollable menu** — the column ⋮ menu container changed `overflow-hidden` → `max-h-[70vh] overflow-y-auto`.
- **#10 friendly name** — a new `utils/tableName.ts::friendlyTableName()` strips the `t_<uuid4>_` prefix (anchored
  to the full uuid shape so a user table containing hex is left alone). **Display-only** — the switcher option and
  the Query Engine table chip *show* the friendly name but still `:value`/insert/seed the **raw** `t_<uuid>_…`
  name the backend requires; the raw name is in the tooltip for transparency.
- **#1 axis numbers** — the reported bug appeared right after TASK-038 added axis titles: a **wide horizontal
  Y-title** was squeezing the value tick numbers off small tiles under the grid's `outerBoundsContain: 'all'`
  (which reserves room for the rect **+ labels + name**, per the installed ECharts type defs). Fix: the two
  cartesian value-axis grids switch to **`outerBoundsContain: 'axisLabel'`** (the classic `containLabel`
  behaviour — the tick-number gutter is always reserved, so numbers show at any size), the Y value-axis **title
  is rotated vertical** (`nameRotate: 90`) so it's a slim strip that can't crowd the numbers, and `grid.left` /
  `grid.bottom` carry a little extra margin for the titles. Heatmap (categorical axes, colour visualMap, no
  numeric axis) is unchanged.

## What changed
### Backend — three files
- **`backend/models/schemas.py`** — `TransformImputeNull.decimals` (#4); `TransformStringNormalize.collapse_whitespace`
  (#3); new `TransformUpdateCell` + added to the `TransformParam` union (#5); `DataResponse.rowids` (#5);
  `QualityFinding.suggested_params` + codes `partial_null` / `inconsistent_values` (#2/#6/#8).
- **`backend/services/quality_service.py`** — canonical-distinct metric + `inconsistent_values` finding (#3/#6);
  type-agnostic `partial_null` finding (#6/#8); `suggested_params` on `mixed_values` (coercing cast, #2),
  `negative_values` (keep ≥ 0, #2) and the normalize suggestions.
- **`backend/services/transform_service.py`** — `.round(decimals)` on mean/median impute (#4);
  `collapse_whitespace` step in `string_normalize` (#3); `_build_updatecell_sql` + `_compile_op` routing (#5).

*(Note: `backend/routers/session.py` and `backend/routers/query.py` in the working tree also carry TASK-040's
materialize endpoint; query.py's `/data` `rowids` addition belongs to this task. `session.py` here is TASK-040.)*

### Frontend — six files + one new util
- **`src/types.ts`** — `DataResponse.rowids`, `ImputeNullOp.decimals`, `StringNormalizeOp.collapse_whitespace`,
  `UpdateCellOp` (+ union), `OpRequest.seed`, `QualityFinding.suggested_params`, quality codes.
- **`src/components/OpDialog.vue`** — `applySeed()` seed→form mapping; decimals + collapse-whitespace controls;
  a benign `update_cell` `OP_META` entry + a `default` case in `buildOp` (both only because `update_cell` joined
  the `OpKind` union — it's grid-driven, never opened here).
- **`src/components/DataQualityPanel.vue`** — Ignore/Restore state (localStorage per session), `activeFindings` /
  `ignoredFindings`, the ignored-issues section, and `onFix` seed pass-through (#2/#7).
- **`src/composables/useSession.ts`** — `updateCell()` (no `dataVersion` bump), exported (#5).
- **`src/components/DataGrid.vue`** — in-cell edit (double-click → input, optimistic patch + rollback), `rowids`
  tracking, scrollable ⋮ menu, friendly names in the switcher (#5/#9/#10).
- **`src/components/QueryConsole.vue`** — friendly name on the table chip (display only) (#10).
- **`src/utils/tableName.ts`** *(new)* — `friendlyTableName()` (#10).
- **`src/components/ChartTile.vue`** — value-axis grids → `outerBoundsContain: 'axisLabel'`, vertical Y-title,
  wider title margins (#1).

## Config
**None.** No env vars, no secrets, no new dependency, no persisted-schema change. `update_cell` adds no
client-controlled SQL text (identifiers validated/quoted, value strictly CAST, fails closed). No LLM/API-key
surface is touched.

## Acceptance criteria
1. **#1** — vertical-bar/line/area/2-D charts keep their value tick numbers at small tile sizes; axis titles still
   render where there's room.
2. **#2** — the `order_date` mixed-values and `quantity` negatives findings each show a Fix that opens the dialog
   pre-filled (coercing cast to DATE / keep ≥ 0), with the dry-run preview still gating.
3. **#3** — a normalize with "collapse repeated spaces" merges `upi` / `u.p.i` / `U.P.I` into one value.
4. **#4** — filling nulls with mean/median offers "round to N decimals" (0–10).
5. **#5** — double-clicking a cell edits it; the change persists, is undoable, and survives reload; grid keeps its
   scroll/sort/search.
6. **#6** — sub-threshold nulls and punctuation/spacing category variants are now flagged.
7. **#7** — a finding can be ignored (hidden from the list + counts) and restored.
8. **#8** — casting a column's type keeps its unrelated missing-values finding visible.
9. **#9** — a long column ⋮ menu scrolls instead of overflowing off-screen.
10. **#10** — the table switcher and Query Engine chip show the friendly stem, but still act on the raw table id.
11. **Strict build green**; `README.md` / `.ai/CURRENT_STATE.md` untouched; no dependency change.

## Verification (real output)
### Backend — live HTTP proof against the running server (`:8000`), real Redis (`:6379`), real DuckDB
The ops/detection were added while the server ran **without `--reload`**, so it was restarted (same launch
command, same fixed dev JWT — Redis + on-disk DuckDB durable, so no data lost). `GET /openapi.json` then listed
`update_cell`, `collapse_whitespace`, `decimals`, `partial_null`, `inconsistent_values`, `suggested_params`. A
scripted proof (register → upload a crafted 12-row messy CSV → scan → apply the fixes → `DELETE` cleanup) ran over
real HTTP through `require_session_owner`. **All 16 checks passed:**

- **Scan (#6/#8)** — `inconsistent_values` on `payment`, `negative_values` on `qty`, **`partial_null` on the
  numeric `amount` column** (proving it's not string-gated — the #8 mechanism), and `mixed_values` on `order_date`.
- **Seeds (#2/#3)** — `inconsistent_values.suggested_params.collapse_whitespace === true`;
  `negative_values.suggested_params` = `{action: keep, predicate: "\"qty\" >= 0"}`;
  `mixed_values.suggested_params` = `{coerce: true, new_type: DATE|DOUBLE}`.
- **#4** — `impute_null mean decimals=2` applies (200, row_count 12) — exercises Ibis `.round()`.
- **#3 end-to-end** — `string_normalize {case: lower, strip_special, collapse_whitespace}` applies, and a
  **re-scan shows the `payment` `inconsistent_values` finding cleared** — the variants genuinely merged.
- **#5** — `update_cell {column: qty, rowid: 0, value: "99"}` applies; `/data` returns a `rowids` array parallel
  to `rows` (12 = 12) and the edited cell is visible (`qty @ rowid 0 == 99`).
- **#2 end-to-end** — applying the suggested `filter_rows "qty" >= 0` drops exactly the 4 negative rows (12 → 8).

### Frontend
- **Strict build** — `npm --prefix frontend run build` (`vue-tsc -b && vite build`): **`✓ built in 2.62s`**, zero
  TS errors across all changed files (only the pre-existing >500 kB chunk-size advisory).

**Env caveat (carried from the Canvas/grid waves):** the preview viewport is **0×0**, so on-screen rendering — the
**#1** axis-title pixel spacing, the **#5** double-click/inline-input interaction, the **#7** Ignore/Restore UI,
the **#9** menu scroll, and the **#10** friendly label — is **your real-browser check**. In-env the authoritative
evidence is the **16/16 HTTP proof** (the exact ops the UI calls, including the merge-after-fix re-scan and the
rowid round-trip) and the **green strict build** (the seed mapping, `update_cell` wiring, and axis-option builder
type-check end to end). For **#1** specifically, the ECharts semantics were resolved from the **installed
`echarts` type definitions** (`GridModel.d.ts`: `'all'` contains rect + labels + name; `'axisLabel'` contains rect
+ labels — the `containLabel` equivalent), since the 0×0 canvas can't be screenshotted.

## Definition of Done
All ten feedback items are implemented with the smallest viable surface each: three backend files (detection +
seeds + two op extensions + rowids) proven by 16/16 live checks, and six frontend files + one util proven by a
clean strict build. `update_cell` adds no unsanitized SQL surface (validated/quoted identifiers, strict CAST,
fail-closed). Must-not-change files untouched; no dependency change. Left in `tasks/active/` for the single
sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. Two 🟡 for your awareness (both deliberate trade-offs matching the feedback's intent); the rest 🟢 / ℹ️.

- **🟢 #2/#3/#4/#6/#8 proven end-to-end, not assumed.** The 16/16 run exercised each new runtime path against real
  DuckDB — including the two that only fail at *runtime* (Ibis `.round()` and the canonical-distinct
  `re_replace` chain) and the raw `update_cell` SQL — and confirmed the #3 fix actually merges the variants (the
  finding clears on re-scan) and the #8 finding is genuinely type-agnostic (it fires on a numeric column).
- **🟢 #5 in-cell edit is a real, safe, undoable transform.** It snapshots + records a history step like any op,
  so undo/redo covers it; the value never reaches SQL as raw text (validated column, int rowid, strict CAST that
  fails closed as 400); and `ORDER BY rowid` over a CTAS keeps rowids contiguous, so successive edits can't hit a
  stale row.
- **🟡 #1 prioritizes tick numbers over axis titles on very small/dense tiles.** `outerBoundsContain: 'axisLabel'`
  guarantees the value **numbers** at any size (your explicit ask), but it does *not* reserve room for the axis
  **titles** (TASK-038) the way `'all'` did — so on a very small tile, or a bar chart with many rotated X labels,
  a title can sit tight or clip at the edge. The vertical Y-title + margin bump mitigate it, but I could not
  confirm pixel spacing at 0×0. **Your call:** (a) accept as-is *(recommended — numbers are the reported bug and
  the requirement was "at any size"; titles are best-effort)*, or (b) a small follow-up that hides axis titles
  below a tile-size threshold so nothing ever clips. Flagging so the trade-off is a conscious choice.
- **🟡 #5 shows the typed text optimistically until the next real reload.** To avoid scrolling you off the cell,
  the grid patches the one cell with your input string rather than re-fetching; for an unusual value the backend
  `CAST` result could differ cosmetically (e.g. `"5.0"` typed into an integer column shows `5.0` until a reload
  shows `5`). The persisted value is always the CAST result; only the transient display can differ. Relatedly,
  the quality panel does **not** re-scan per keystroke-commit (it re-scans on the next transform/undo) — a
  deliberate choice to avoid a whole-table re-query per cell edit. **Recommended: accept** — both keep single-cell
  editing cheap and non-disruptive.
- **🟢 #7 Ignore is stable across re-scans and never hides real changes.** Dismissals key off the stable
  `"{code}:{column}"` id, so a genuinely new issue (new column/new code) still surfaces; the ignored set is
  reloaded per session and shown in a restore-able list, so nothing is silently lost.
- **🟢 #10 friendly name is display-only.** The switcher and chip render `friendlyTableName()` but still
  `:value`/insert/seed the raw `t_<uuid>_…` id, and the prefix regex is anchored to the full uuid4 shape, so a
  user table that merely contains hex is left untouched. No API call receives the friendly string.
- **ℹ️ #6/#8 `partial_null` is intentionally noisier.** It now fires on *any* sub-threshold null, so a dirty table
  can show several new low-severity findings. That's the point of "stronger detection" — and they're low severity
  and dismissible via #7. If it proves too chatty in practice, a minimum-count/percent floor is a one-line tweak.
- **ℹ️ #7 Ignore is client-local (localStorage), not server-persisted.** Dismissals don't sync across
  browsers/devices and are cleared with site data. This matches the frontend-only scope of the feedback and
  avoids a new endpoint + schema; say the word if you want it persisted server-side per user.
- **ℹ️ #1 mechanism is documented from the installed ECharts types, not a live screenshot.** The 0×0 canvas can't
  be imaged; the `'axisLabel'` choice is the library's own `containLabel` equivalent (verified in
  `echarts/types/.../GridModel.d.ts`), and the option builder type-checks. On-screen spacing remains your check.
- **ℹ️ Server restart was required** to load the new ops/detection (no `--reload`). Done with the identical launch
  command; durable Redis + on-disk DuckDB and the fixed dev JWT kept it transparent to any open browser session.
