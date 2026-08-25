# TASK-038 — Chart axis controls: X/Y-labeled field pickers + on-chart axis titles

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
You asked: *"do that axis thing in the charts — it should ask what['s] on the x axis, what['s] on the y
axis, and it should show in the chart what['s] on the x axis, what's on the y axis."*

Two gaps made the axis mapping feel absent, even though the machinery was already there:
1. **The pickers didn't read as axis selectors.** A chart tile already had Dimension / Measure / Aggregation
   `<select>`s that set the X field (`config.dimension`), the Y field (`config.measure`) and its aggregation —
   but they were labeled in BI jargon (**"Dimension" / "Measure"**), so it wasn't obvious *that* was how you
   choose what goes on X and Y.
2. **The rendered chart drew no axis titles at all.** The ECharts option set no axis `name` anywhere, so once
   a chart was drawn you couldn't see which field was on which axis.

Frontend-only. **No new dependency, no backend change, no wire-contract change, no new config field or
secret.** One file touched: `components/ChartTile.vue`.

## Approach & why
- **Relabel the pickers by *where the field lands on the plot*, per chart type.** A new `axisLabels` computed
  maps `config.chartType` → the label strings, so the editor always agrees with the drawn axes:
  - bar / line / area / stacked → dimension = **"X axis"**, measure = **"Y axis"**
  - **hbar** (axes swap) → dimension = **"Y axis"**, measure = **"X axis"**
  - **heatmap** (2-D) → dimension = **"X axis"**, breakdown = **"Y axis"**, measure = **"Value (colour)"**
  - **pie / treemap / funnel** (no axes) → dimension = **"Category"**, measure = **"Value"**

  The picker **wiring is unchanged** — same `<select>`s, same `onDimensionChange`/`onMeasureChange`/`onAggChange`
  handlers, same `config` fields. Only the `<label>` text is now bound to `axisLabels`. The empty-state hint
  likewise became `Choose a field for the {X axis|Y axis|Category}.` so the *ask* is explicit before any field
  is picked.
- **Draw the axis titles from the fields that already exist.** The two axis builders in the `option` computed
  (`makeCategoryAxis`, and `valueAxis` → now a `makeValueAxis(name, nameGap)` factory) take an optional axis
  **`name`** and render it with `nameLocation: 'middle'`, a `nameGap`, and a shared `axisNameStyle`
  (`CHART_INK`/`CHART_FONT`, 12px, semibold). The category-axis title is `config.dimension`; the value-axis
  title is the existing `measureLabel` (e.g. *"Sum of revenue"*). Because the existing cartesian frame already
  assigns category→Y / value→X for `hbar`, the **titles swap with the axes for free**. For the 2-D breakdown
  frame the Y (value) axis gets `measureLabel` and the heatmap's Y (category) axis gets the breakdown
  (`config.series`). Pie/treemap/funnel have no axes and are untouched.
- **Reserve gutter for the titles so they never clip.** The `grid` used
  `outerBoundsContain: 'axisLabel'`, which (per the ECharts 6 docs) reserves room for tick labels **but
  excludes axis names**. Switched all three cartesian grids to **`outerBoundsContain: 'all'`**, which
  "constrains the grid rectangle, axis labels, **and axis names**" — ECharts shrinks the plot to fit the
  titles rather than clipping them. `nameGap` is biased large (rotated X labels 60, flat Y category labels 72,
  Y value 54, X value on hbar 30) so a title clears its tick labels; with `'all'` any excess only reserves
  gutter, it never spills off-canvas.
- **No new persisted state.** Titles are derived from `dimension`/`measure`/`aggregation`, which already
  persist — nothing new in the dashboard blob, so old saved dashboards get titles automatically. A refetch is
  only needed when a *query* field changes, which `ChartCanvas.onChartUpdate` already handles; relabeling and
  title-drawing add no fetch.

## What changed
### Frontend (only) — one file: `components/ChartTile.vue`
- **New `axisLabels` computed** — `{ dim, series, measure }` label strings switched on `config.chartType`
  (table above).
- **New `axisNameStyle`** const next to `axisLabelStyle` (12px semibold title style).
- **`makeCategoryAxis(labels, flat, name?)`** — now takes an optional `name` and emits
  `name`/`nameLocation`/`nameGap`/`nameTextStyle`; `nameGap` = 72 (flat Y category) / 60 (rotated X) / 30
  (flat X). Existing rotate logic preserved.
- **`valueAxis` → `makeValueAxis(name?, nameGap = 54)`** factory — emits the same title props; callers pass
  `nameGap: 30` when it sits on X (hbar).
- **Wiring** — 1-D cartesian, 2-D breakdown, and heatmap frames now pass `config.dimension` /
  `measureLabel.value` / `config.series` as axis names; all three grids switched to
  `outerBoundsContain: 'all'`.
- **Template** — the three picker `<label>`s bind to `axisLabels.dim` / `.series` / `.measure`; the
  Aggregation and Type labels are unchanged; the empty-state hint names the axis.

No change to `types.ts`, `ChartCanvas.vue`, any composable, the backend, the wire contract, or dependencies.

## Config
**None.** No env vars, no secrets, no client-controlled server surface, no new dependency, no new persisted
config field (titles derive from existing `dimension`/`measure`/`aggregation`).

## Acceptance criteria
1. **Pickers read as axes** — a bar chart's field pickers are labeled **X axis** (was "Dimension") and
   **Y axis** (was "Measure"); the empty state asks for *"a field for the X axis."*
2. **Labels track the chart type** — switching to **hbar** swaps them (dimension→**Y axis**, measure→**X
   axis**); **pie/treemap/funnel** read **Category** / **Value**; **heatmap** reads **X axis** / **Y axis** /
   **Value (colour)**.
3. **Titles drawn on the chart** — the category axis shows the dimension field name and the value axis shows
   the measure label (e.g. *"Sum of revenue"*); the titles swap correctly for hbar; pie/treemap/funnel show
   none.
4. **No clipping / no overlap** — titles sit clear of the tick labels and stay on-canvas (`outerBoundsContain:
   'all'` + biased `nameGap`).
5. **No refetch on relabel / retitle** — changing chart type (a non-query field) redraws from data in hand;
   only query-field changes fetch (unchanged behaviour).
6. **Present/export** — titles are part of the ECharts canvas, so they appear in the PNG/PDF/Present output.
7. **Strict build green** — `vue-tsc -b && vite build` clean.
8. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire/dependency change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user (user id 7), Canvas with a
seeded dataset (`region` categorical + `revenue` numeric, 12 rows) and a live bar tile *"Sum of revenue by
region"*. Chart types were driven by dispatching real `change` events on the Type `<select>`, and the ECharts
option was decoded from the live instance (`getInstanceByDom(host).getOption()`).

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 4.23s`, zero
  TS errors.**
- **Picker labels (Part 1)** — the live editor strip reads **`["X axis", "Breakdown", "Y axis",
  "Aggregation", "Type", "Show top"]`** (was Dimension/Breakdown/Measure/…).
- **Bar axis titles (Part 2)** — decoded option: `xAxis = { type: 'category', name: "region",
  nameLocation: 'middle', nameGap: 30 }`, `yAxis = { type: 'value', name: "Sum of revenue",
  nameLocation: 'middle', nameGap: 54 }`, `grid.outerBoundsContain: 'all'`.
- **hbar swaps both label and title** — after switching to hbar: editor labels became **`["Y axis", "X axis",
  …]`**; option `xAxis = { type: 'value', name: "Sum of revenue", nameGap: 30 }`, `yAxis = { type: 'category',
  name: "region", nameGap: 72 }`.
- **pie** — editor labels **`["Category", "Value", …]`**; option has **no** `xAxis`/`yAxis` (`hasX:false,
  hasY:false`), series `pie`.
- **heatmap** — editor labels **`["X axis", "Y axis", "Value (colour)", …]`**.
- **Restore** — switching back to bar restored labels **`["X axis", "Breakdown", "Y axis", …]`** and axis
  names `region` / `Sum of revenue`; the tile was left on its original type (canvas unchanged).
- **No errors** — `preview_console_logs (error)` clean across all the type switches.

**Env caveat (carried from the Canvas wave):** the preview viewport is **0×0**, so the *on-screen pixel
spacing* of the titles — that the biased `nameGap`s clear the labels and the `'all'` gutter looks balanced
on a real tile — is the **user's real-browser check**. Everything else is authoritative and exercised above:
the label text, the decoded axis `name`/`nameLocation`/`nameGap`, `outerBoundsContain: 'all'`, the per-type
swap logic, and a clean console.

## Definition of Done
The chart field pickers are labeled as **X axis / Y axis** (Category / Value for the axis-less shapes,
swapped for horizontal bars), so choosing what goes on each axis is explicit; and every cartesian chart draws
those field names as axis titles, derived from the existing config with no new persisted state and no extra
fetch. Strict build clean; must-not-change verified; no backend/dependency/wire change. Left in
`tasks/active/` for the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 judgment call for your sign-off; the rest 🟢 / ℹ️.

- **🟡 `nameGap` values are heuristics, not measured.** The gaps (72/60/54/30) are chosen to clear typical
  tick labels, but a very long category label (a wide hbar Y-axis value) or a very short tile could leave the
  title a little close to, or a little far from, the labels. With `outerBoundsContain: 'all'` it can't clip
  off-canvas — the worst case is spacing that looks slightly loose/tight. **Your call:** keep the fixed gaps
  (recommended — simple, and the option is provably correct; tune only if a real dataset looks off), or I can
  compute `nameGap` from the measured max label extent for pixel-tight spacing.
- **🟢 Titles derive from existing state — no migration, no new fetch.** Names come from `config.dimension`
  and `measureLabel`; nothing new persists, so saved dashboards gain titles on next render, and changing a
  non-query field (chart type) redraws without hitting `/aggregate` (verified: labels/titles updated with no
  network).
- **🟢 Per-type mapping verified end-to-end.** bar / hbar / pie / heatmap each produced the correct editor
  labels **and** (for cartesian) the correct decoded axis `name`s, including the hbar axis swap and the
  axis-less pie. Restoring to bar returned the original state.
- **🟢 `outerBoundsContain: 'all'` is the documented fix.** Per the ECharts 6 grid docs, `'axisLabel'`
  excludes axis names (would clip titles) and `'all'` includes them; confirmed the live option carries `'all'`
  on the cartesian grids.
- **🟢 Present/export unaffected in the right way.** Axis titles live in the ECharts canvas (not a
  `js-export-exclude` DOM node), so they correctly *appear* in exported/presented charts — which is the
  desired behaviour for a titled axis.
- **ℹ️ Titles are auto-derived, not editable.** This matches your ask ("show *what's* on x/y"). If you later
  want to override an axis caption with custom text, that's a small follow-up: add optional `xTitle`/`yTitle`
  to `ChartConfig` + two inputs — deferred to keep this scoped.
- **ℹ️ Numeric columns still aren't offered for the X/dimension picker.** `dimensionColumns()` excludes them
  (the current chart types are category-vs-measure). A numeric X (scatter) would be a new chart type — out of
  scope here.
- **ℹ️ ChartTile colour popover Teleport (from TASK-037) still open as a follow-up.** Untouched here to keep
  this task scoped to the axis feature; happy to apply it whenever you want.
