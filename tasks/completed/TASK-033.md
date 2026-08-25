# TASK-033 — Power BI Canvas, part 1: per-tile presentation controls + live auto-persist

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
First slice of the Power BI–style Canvas upgrade. Delivers the per-tile presentation features and the
persistence foundation the rest of the upgrade rides on — **frontend-only, no new dependencies**:

- **#2 Editable per-tile title** — override the auto-derived `"Sum of revenue by region"`.
- **#3 Change chart color** — recolor a single-series chart / a KPI's sparkline accent.
- **#4 Show values/counts on the chart** — data labels on the plot (today hard-`false`).
- **#5 Per-tile "clean" toggle** — hide the tile's controls, keep just the title + chart.
- **#7 (per-tile) Present** — already delivered by TASK-032's `.dashboard-clean`/`js-export-exclude`
  contract; this task **completes it for KPI cards** (their action group was missing the class).
- **Auto-persist the live board** ("persist immediately") — the board no longer evaporates on reload.

Movable/resizable tiles (#1) and multiple pages (#6) are the next task (TASK-034); named Save/Load slots
are TASK-035. This task deliberately ships the low-risk presentation layer + the persistence seam first,
so everything downstream inherits "persist immediately" from the very first field.

## Approach & why
- **Optional config fields (back-compat).** `ChartConfig` gains `title?`, `color?`, `showValues?`,
  `hideControls?`; `KpiConfig` gains `title?`, `accent?`, `hideControls?`. All optional ⇒ existing tiles
  and any saved dashboard render exactly as before (matches the "optional additions are back-compat by
  design" note already on `KpiConfig`).
- **Editable title.** `title` becomes `config.title?.trim() || autoTitle`, so every existing consumer
  (export filename, #18 explain spec, #30 recommend) automatically uses the override. ChartTile edits it
  **inline in the header** (QueryConsole's `savingName` idiom: input + `@keydown.enter`/`.esc`, pencil to
  open, confirm on blur). KpiCard edits it as the first field of its **existing inline editor panel** —
  each tile uses the editing affordance already native to that component (flagged in self-review).
- **Color.** A swatch popover (ResultsTable's `menuOpen` + `fixed inset-0` backdrop idiom — no document
  listeners), swatches sourced from `chartPalette.ts` `CHART_PALETTE` (8 on-brand oklch hues) + a
  **Default** reset. In ChartTile it overrides `CHART_PRIMARY` for the **single-series** cartesian shapes
  (bar/line/area/hbar); a breakdown keeps the categorical palette (the popover says so). In KpiCard it
  drives the sparkline `stroke` via `currentColor` (`:style="{ color: accent }"`).
- **Data labels.** A shared `showValues` flag turns on ECharts `series.label` across every shape, with the
  tile's own number formatting (`toLocaleString`, max 2 fractional digits): bar/line/area/hbar/stacked and
  the 2-D multi-series get value labels; heatmap cells get their value; pie shows `name: value`;
  treemap/funnel **keep their name label and append the value** when on (so turning the flag off is not a
  regression from their current always-on name label). `label` is a built-in series property in the
  modular ECharts build — **no new module import**.
- **Clean toggle.** `hideControls` collapses the control strip (already `js-export-exclude`) while keeping
  the title + plot. A small always-available presentation toolbar (color / values / clean / remove) stays
  so the tile can be reconfigured or un-cleaned; it is itself `js-export-exclude`, so present/export hide
  it too — leaving only title + chart, exactly like feature #7.
- **KpiCard `js-export-exclude` fix.** The KPI action group (`KpiCard.vue`) was **not** tagged (unlike
  ChartTile), so present/export did not hide KPI chrome. Tagging it completes the present contract for
  KPIs.
- **Auto-persist ("persist immediately").** A new per-user store `useActiveDashboard.ts` mirrors the
  `useDashboards`/`useQueryHistory` idiom (per-user `k(base)` key `spencer.activeDashboard:<userId>`,
  tolerant read, swallow-on-quota write, `JSON.parse(JSON.stringify(...))` clone). Blob **v1** =
  `{ v:1, sessionUuid, snapshot:{ kpis, charts } }`. `useAuth.applyUserScope` calls its `loadForUser`
  alongside the other stores. `ChartCanvas` `watch([kpis,charts], …, {deep:true})` persists on every
  edit; the `sessionUuid` seed watch **rehydrates** the blob only when `blob.sessionUuid === current`
  (else seeds fresh). The persist watch **returns early when `sessionUuid` is null**, so the reset-to-`[]`
  that fires on logout/replace never stomps a good blob (the exact ordering hazard exploration flagged).

## What changed
### Frontend (only) — no backend, no wire contract, no new config/secret, no new dependency
- **`types.ts`** — optional presentation fields on `ChartConfig` + `KpiConfig`; new
  `ActiveDashboardBlobV1` persistence contract.
- **`composables/useActiveDashboard.ts`** (new) — per-user active-board read/write utility
  (`loadForUser`, `readActiveDashboard`, `persistActiveDashboard`, `clearActiveDashboard`).
- **`composables/useAuth.ts`** — `applyUserScope` also scopes the active-dashboard store.
- **`components/ChartTile.vue`** — inline-editable title; color swatch popover (single-series override);
  `showValues` data labels across all shapes; `hideControls` clean toggle; a hover presentation toolbar
  (color/values/clean/remove) inside the existing `js-export-exclude` header zone.
- **`components/KpiCard.vue`** — title field in the editor panel; accent color popover → sparkline;
  `hideControls` clean toggle; **action group now carries `js-export-exclude`** (the fix).
- **`components/ChartCanvas.vue`** — import + wire the active-dashboard store; deep `watch([kpis,charts])`
  persist (null-session guarded); rehydrate-or-seed in the `sessionUuid` watch; an **explicit persist in
  the seed branch** (the immediate `sessionUuid` watch runs the seed synchronously at setup, *before* the
  deep watch registers, so the seed mutation isn't observed — the explicit write makes an unedited seeded
  board survive a reload); advance the id counters past restored ids; header comment updated.

## Config
**None.** No env vars, no secrets, no client-controlled server surface. `localStorage` only, per-user
namespaced.

## Acceptance criteria
1. **Editable title** — ChartTile pencil opens an inline input; a custom title renders in the header,
   feeds the PNG filename/explain/recommend, and **survives a reload**; clearing it reverts to the auto
   title. KpiCard title field in its editor does the same.
2. **Chart color** — a ChartTile single-series bar/line recolors to the picked swatch (ECharts `option`
   `itemStyle.color`/`lineStyle.color` = the swatch); "Default" restores `CHART_PRIMARY`; a KPI sparkline
   recolors via `currentColor`.
3. **Data labels** — toggling values on makes bar/line/etc. render numeric labels
   (`series.label.show === true`); off restores the clean plot.
4. **Clean toggle** — hides the tile's control strip while keeping title + chart; reversible; the state
   persists.
5. **Present contract (KPI)** — in `.dashboard-clean`, the KPI action group computes `display:none` (it
   now carries `js-export-exclude`); the KPI title/value/spark stay.
6. **Auto-persist** — after any tile edit, `localStorage[spencer.activeDashboard:<uid>]` holds a `v:1`
   blob with the current session uuid + snapshot; **reload restores the exact board**; a foreign/absent
   session seeds fresh; logout/replace (`sessionUuid → null`) does **not** overwrite the blob with empties;
   a second user does not see the first's board (per-user key).
7. **Strict build green** — `vue-tsc -b && vite build` clean.
8. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire/dependency change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user `uid=7`, dataset
`spark_demo.csv` (`order_date` DATE, `region` VARCHAR, `revenue` BIGINT; 12 rows) — a temporal +
categorical + numeric schema that exercises sparklines, single-series bars, and data labels.

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2739 modules, `✓ built in 2.52s`,
  zero TS errors**. (Pre-existing >500 kB chunk-size warning only; unrelated to this change.)
- **Auto-persist seed (#6)** — on Canvas mount, `localStorage['spencer.activeDashboard:7']` =
  `{ v:1, sessionUuid:'2a46540b…', snapshot:{ kpis:3, charts:1 } }`, entries shaped `{id, config}`.
- **#2 chart title** — inline pencil → input → Enter: DOM `<h3>` **and** blob both read
  `"Revenue by Region (LIVE TEST)"` (spaces + parens preserved ⇒ raw-emit confirmed, no per-keystroke trim).
- **#6 reload restores** — hard `location.reload()` → Canvas rehydrated the **custom** title from
  localStorage (`"Revenue by Region (LIVE TEST)"`), not the auto-seed `"Sum of revenue by region"`.
- **#4 data labels** — "Show values" toggle → blob `charts[0].config.showValues === true`.
- **#3 chart color** — swatch pick → blob `charts[0].config.color === 'oklch(0.587 0.174 252.167)'`
  (picked swatch's `title` matched the stored value ⇒ correct wiring).
- **#3 KPI accent** — swatch pick → KPI#0 sparkline `<svg>` inline `style="color: oklch(0.68 0.14 64)"`
  and its `<polyline>` computed `stroke === oklch(0.68 0.14 64)` (via `currentColor`); KPI#1/#2 (no accent)
  keep the brand default `oklch(0.587 …)`. `getComputedStyle`-authoritative.
- **#5 chart clean** — "Hide controls" → picker `<select>` count **5 → 0** in the tile; the `<h3>` title
  and the chart `<canvas>` remain; blob `hideControls === true`.
- **#5 KPI clean** — "Hide controls" → the editor panel (its `<input>`) is removed; blob `hideControls === true`.
- **#5 present contract (KPI, the fix)** — applying `.dashboard-clean` to the capture root:
  KPI action group `getComputedStyle().display` **`flex → none`** (it now carries `js-export-exclude`),
  KPI value stays `block`, chart chrome also `none`; removing the class → back to `flex`.
- **No console errors** during the whole session; board reset to a pristine seed afterward (verified: chart
  title back to auto, no presentation fields on any tile).
- **#8 must-not-change** — `git diff` shows `README.md` and `.ai/CURRENT_STATE.md` untouched; **no new
  dependency** (no `npm install`; no new package import). TASK-033 file footprint: `ChartCanvas.vue`,
  `ChartTile.vue`, `KpiCard.vue`, `useAuth.ts`, `types.ts`, + new `useActiveDashboard.ts`.

**Env caveat (carried from TASK-032):** ECharts uses the `CanvasRenderer`, and the preview viewport is 0×0,
so the **on-canvas paint** of the recolored bar and the data labels is the **user's real-browser check**.
In-env the config→`option` mapping is pure and type-checked (green build), and the config that drives it is
proven to flip + persist above; the KPI accent (inline SVG) is directly `getComputedStyle`-verified.

## Definition of Done
The Canvas tiles have editable titles, per-chart color, on-graph value labels, and a per-tile clean
toggle; KPI chrome is hidden in present/export; and the live board auto-persists per user so a reload
restores it. Strict build clean; must-not-change verified. Left in `tasks/active/` for the single
sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. Two 🟡 UX judgment calls for your sign-off; the rest are ℹ️/🟢 notes.

- **🟡 Color on a broken-down chart is a silent no-op.** `#3` is scoped to single-series shapes; when a
  breakdown (`series`) is active the categorical palette wins, so a picked `color` is stored + the Palette
  button lights "active" but the plot doesn't change. Mitigation: the popover explicitly says *"a breakdown
  uses the category palette."* I kept the value stored (removing the breakdown later reveals it) rather than
  disabling the button. **Your call:** acceptable, or disable the Palette button while a breakdown is set?
- **🟡 "Clean" keeps a hover toolbar; only Present is fully bare.** `hideControls` hides the metric/dimension
  strip but leaves a small hover toolbar (color/values/clean/remove, itself `js-export-exclude`) so the tile
  can be un-cleaned/recolored in place. The truly chrome-free view is **Present** (fullscreen), where that
  toolbar is also hidden — exactly feature #7. **Your call:** is "tidy but still editable on hover" the right
  read of clean, with Present as the bare view?
- **ℹ️ Seed-persist needed an explicit write (plan deviation).** The plan assumed the deep `watch` would
  capture the initial seed; in practice the immediate `sessionUuid` watch seeds *synchronously at setup,
  before* the deep watch registers, so the seed isn't observed. Added one explicit `persistActiveDashboard`
  in the seed branch (verified: blob present on a fresh seed). Ongoing edits still ride the deep watch.
- **ℹ️ KPI title persists per keystroke; ChartTile on confirm.** KpiCard edits the title in its panel and
  emits on `@input` (raw; null only if all-whitespace), so each keystroke writes the (small) blob; ChartTile
  edits inline and emits once on enter/blur. Both correct; not debounced — consistent with
  `useDashboards`/`useQueryHistory`, which don't debounce either. Also the intended UX asymmetry (each tile
  uses its component's native editing affordance).
- **🟢 treemap/funnel labels append the value, keep the name.** So toggling values *off* is not a regression
  from their current always-on name label (pie/heatmap/cartesian gate the whole label on the flag).
- **🟢 Rehydrate is well-guarded.** Foreign/absent/empty snapshot → seed fresh; null session → persist
  early-returns (single-flush batching means the reset-to-`[]` intermediate never reaches disk, so a good
  blob is never stomped on logout/replace); id counters resume at `maxId+1` (no collisions). Same-dataset
  restore only (uuid changes on replace), so a restored config never points at a dropped column.
- **🟢 Back-compat.** Every new field is optional; a tile/dashboard without them renders exactly as before
  (title→auto, color→`CHART_PRIMARY`, showValues→false, hideControls→false). Build green with the additions.
- **ℹ️ Verification mutated the live `uid=7` demo board**, then reset it to a pristine seed (confirmed). No
  lasting change to your data.
