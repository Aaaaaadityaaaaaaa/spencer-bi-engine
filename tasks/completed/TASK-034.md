# TASK-034 — Power BI Canvas, part 2: unified movable/resizable grid + multiple pages

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
Second slice of the Power BI–style Canvas upgrade. Turns the two fixed CSS grids into **one freeform,
movable + resizable surface** and adds **named pages** — the two structural features the dashboard was
missing. Frontend-only; adds one dependency (`grid-layout-plus`, already vendored).

- **#1 Movable + resizable + snapping tiles** — KPI cards and charts share a single drag/resize grid
  (true Power BI), not two separate `grid-cols-*` blocks. Drag repositions with collision-aware
  compaction; resize re-renders the chart to the new box.
- **#6 Multiple named pages** — the board is a list of pages, each owning its own tiles + layout; a tab
  bar switches/adds/renames/deletes them.
- **#7 (page-level) Present** — fullscreen shows only the **active page**, clean, with drag/resize
  disabled (rides TASK-032's `.dashboard-clean`/`js-export-exclude` contract; the page tab bar is
  excluded too).
- **v1 → v2 persistence upgrade** — a board saved by TASK-033 (single page, no grid) is migrated on read
  into one "Page 1" with a synthesized flow layout, so "persist immediately" survives the grid upgrade.

Named Save/Load slots are TASK-035. This task isolates the one risky piece (the grid refactor + the
multi-page reshape of the persisted board) behind a green build and the live checks below.

## Approach & why
- **One unified grid, tiles keyed by a composite id.** A single `<GridLayout>` renders `<GridItem v-for>`
  over a `TileLayout[]` (`{ i, x, y, w, h }`), where `i` is `"kpi:<id>"` / `"chart:<id>"`. The **fetch
  layer is unchanged** — `loadKpi`/`loadChart` still key on the numeric id; only *placement* is new. A
  `parseTileId` helper maps `i` back to the config for rendering, and to per-kind min-size (`CHART_MIN_*`
  vs `KPI_MIN_*`).
- **`grid-layout-plus`** (v1.1.1, MIT, Vue-3, serializable layouts) — chosen over hand-rolling
  drag/resize math. Bound **one-way** (`:layout`, not `v-model`): the library mutates the bound array
  **in place** during a gesture and emits `layout-updated` on release; a one-way bind + a debounced deep
  watch for persistence + an `@layout-updated` synchronous commit avoids a `v-model` write-back loop while
  still capturing every move.
- **Drag only by a grip.** `drag-allow-from=".tile-drag-handle"` is a **whitelist** — only the small
  grip in each tile header initiates a drag, so every picker / button / `<select>` / inline input inside
  a tile stays fully clickable with **no** `drag-ignore-from` needed. (Critically, the grip itself is
  `js-export-exclude`, so it must *not* appear in any ignore selector.)
- **Pages as the source of truth; `kpis`/`charts`/`layout` are read-only views** over the active page
  (`computed(() => activePage.value?.X ?? [])`). Every existing edit/fetch/cross-filter path reads them
  unchanged; add/remove/page ops mutate the `DashboardPage` objects directly (and keep `layout` in
  lockstep — push a `TileLayout` on add, splice it on remove).
- **ECharts resize is free.** `useEchart`'s `ResizeObserver` already re-renders when the plot box
  changes; a resizable tile whose plot is `flex-1 min-h-0` re-renders with no extra wiring.
- **Counter resumption across ALL pages.** `resetCountersFromPages()` sets `nextKpiId`/`nextChartId` to
  `max(id over every page) + 1`, so a tile added on page 2 can never collide with a restored id on page 1
  (which would clobber its fetch state).
- **v1 → v2 upgrade on read + migrate on first load.** `readActiveDashboard` upgrades a `v:1` blob by
  wrapping `{ kpis, charts }` into one `"page-1"` with `generateFlowLayout`. The `sessionUuid` seed watch
  then **persists v2 for both the seed and the restore path** (an explicit `persistNow()` after the
  branch), so an upgraded board is written back as v2 on first load rather than re-upgraded from v1 on
  every reload. `reconcilePageLayout` self-heals a hand-edited blob (drops orphan layout items, appends
  any tile missing one).
- **Page delete is guarded.** Always keeps ≥ 1 page; a *populated* page prompts `window.confirm` first
  (deletion persists immediately, so it's hard to reverse); switching pages clears the cross-filter (a
  per-view slice) and refetches the new page's tiles.

## What changed
### Frontend (only) — no backend, no wire contract, no new config/secret
- **`package.json`** — `+ "grid-layout-plus": "^1.1.1"` (MIT; Vue-3 peer; CSS auto-injected).
- **`utils/dashboardLayout.ts`** (new) — grid constants (`GRID_COLS=12`, `GRID_ROW_HEIGHT=40`,
  `GRID_MARGIN`, per-kind default + min sizes), composite-id helpers (`kpiTileId`/`chartTileId`/
  `parseTileId`), `layoutBottom`, and `generateFlowLayout` (KPIs across the top, charts below).
- **`types.ts`** — `TileLayout`, `PersistedChartEntry`, `DashboardPage`; **reshaped** `DashboardSnapshot`
  to `{ pages, activePageId }`; `SavedDashboard extends DashboardSnapshot`; new `ActiveDashboardBlobV2`
  (kept `ActiveDashboardBlobV1` + `ActiveDashboardSnapshot` for the upgrade path).
- **`composables/useActiveDashboard.ts`** — reads/writes **v2**; `upgradeV1` migrates a pre-grid blob;
  `isValidPage` guards each restored page; `persistActiveDashboard` writes `{ pages, activePageId }`.
- **`components/ChartCanvas.vue`** — the big refactor: pages model + read-only `kpis`/`charts`/`layout`
  views; one `<GridLayout>` over the active page; a page tab bar (add/switch/inline-rename/delete);
  debounced deep-watch persist + `@layout-updated` synchronous commit; `reconcilePageLayout`; counter
  resumption across pages; present/export extended to drop the grid resize handles + tab bar.
- **`components/KpiCard.vue`** / **`components/ChartTile.vue`** — a `.tile-drag-handle` grip in each
  header (the sole drag origin; `js-export-exclude`, hover-revealed); each tile fills its GridItem
  (`h-full`), and ChartTile's plot is `flex-1 min-h-0` so a resize re-renders ECharts via the existing
  `ResizeObserver`.

## Config
**None.** No env vars, no secrets, no client-controlled server surface. `localStorage` only, per-user
namespaced (`spencer.activeDashboard:<userId>`). One new npm dependency; no runtime configuration.

## Acceptance criteria
1. **Unified grid** — KPI cards + charts render in one `<GridLayout>`; each tile has a drag grip; a tile
   is dragged only by its grip (pickers/buttons stay clickable).
2. **Move** — dragging a tile repositions it with collision-aware compaction; the new layout persists
   and survives a reload.
3. **Resize** — resizing a chart tile re-renders ECharts to the new box; the new `w/h` persists.
4. **Pages** — add a page (auto-named, becomes active, blank + empty hint); rename inline; delete
   (guarded: keeps ≥1, confirms a populated page); switching shows that page's tiles/layout only.
5. **Per-page isolation** — editing/adding a tile on one page does not touch another; each page persists
   its own tiles + layout.
6. **Counter resumption** — a tile added after a restore gets an id past every restored id on every page
   (no collision).
7. **Present (page-level)** — fullscreen shows only the active page, clean; drag/resize disabled; tab bar
   + grips + resize handles hidden.
8. **v1 → v2 upgrade** — a TASK-033 `v:1` blob loads as one "Page 1" with a flow layout (configs +
   custom titles preserved) and is rewritten to `v:2` on disk on first load.
9. **Strict build green** — `vue-tsc -b && vite build` clean.
10. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user `uid=7`, dataset
`spark_demo.csv` (`order_date` DATE, `region` VARCHAR, `revenue` BIGINT; 12 rows).

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 2.96s`,
  zero TS errors**. (Pre-existing >500 kB chunk-size warning only.)
- **Unified grid renders** — one `.vgl-layout`; **4 seeded tiles** (`kpi:1/2/3` + `chart:1`), each with a
  `.tile-drag-handle` grip, + 1 hidden drag placeholder (`.vgl-item` count = 5). All 4 tiles show data:
  `TOTAL ROWS 12`, `SUM OF REVENUE 1,670`, `AVERAGE OF REVENUE 139.17`, `Sum of revenue by region`.
- **Layout math exact** — KPI tiles `height:144px` (`3·40 + 2·12`), chart tile `height:404px`
  (`8·40 + 7·12`), chart stacked at `y:168px` (`144 + 12 + 12`). Y axis is fixed-`rowHeight`, so it's
  authoritative in-env; X spacing is width-driven (see env caveat).
- **v1 → v2 upgrade + on-disk migration** — planted a genuine `v:1` blob (2 KPIs incl. a custom
  `title:"Legacy rows"`, 1 chart) for the current uuid → reload → on disk now `v:2`, one `"Page 1"`,
  layout `["kpi:5","kpi:6","chart:9"]`, **custom title preserved**, 3 grips render. Confirms the upgrade
  *and* the both-paths `persistNow()` rewrite (no re-upgrade on every reload).
- **#4 add page** — `+ Page` → `pages:2` `["Page 1","Page 2"]`, new page id `pg-…` (seed-id format, not
  the upgrade's `page-1`), becomes active, blank (`kpis:0,charts:0`), **"This page is empty" hint** shows,
  `<GridLayout>` correctly hidden (`v-if` on `layout.length>0`).
- **#5 per-page isolation + #6 counter resumption** — Add KPI on Page 2 → Page 1 unchanged
  (`kpi:5/6/chart:9`), Page 2 gets **only** `kpi:7`; **id 7 > restored ids 5,6** ⇒ counter resumed across
  pages, no collision.
- **All aggregates 200** — the 7 current-board aggregate calls (3 KPI scalars + 3 trends + 1 chart) all
  returned `200`; **no console/compile errors** across the whole drag-of-state/page/save session (the one
  logged `400` was a *test artifact* — a planted `count_distinct` on a null measure — and did not recur
  on the clean board).
- **Cleanup** — test artifacts (`Legacy rows` board, `Page 2`, saved slot) removed; the `uid=7` board
  reset to a pristine fresh v2 seed (1 page, `pg-…` id, 4 tiles). No lasting change to your data.

**Env caveat (carried from TASK-032):** the preview viewport is **0×0**, so a real pointer **drag/resize
gesture**, real OS **fullscreen** present, and the whole-board **PNG/PDF raster** are the **user's
real-browser check**. In-env the layout **state** is authoritative and fully exercised (GridItem props,
persisted `TileLayout`, per-page isolation, counter resumption, v1→v2 migration — all above); only the
pointer-driven gesture and the 0×0-blocked raster remain for a real browser.

## Definition of Done
KPI cards and charts live on one movable/resizable grid; the board has named, switchable pages; present
shows only the active page, clean; and a pre-grid board migrates cleanly to the multi-page shape. Strict
build clean; must-not-change verified. Left in `tasks/active/` for the single sign-off. **Not
self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 UX judgment call for your sign-off; the rest are ℹ️/🟢.

- **🟡 A tile added on a page you can't see still lands there silently.** Add KPI/Add chart append to the
  **active** page. If you add while Present or on a different tab than you meant, the tile lands on the
  active page (correct, but there's no toast). Mitigation: the empty-page hint + the tab's tile count make
  it discoverable. **Your call:** fine as-is, or add a brief "added to <page>" confirmation?
- **ℹ️ Restore path now persists (plan refinement over TASK-033).** TASK-033 only wrote in the seed
  branch; I moved `persistNow()` to run for **both** seed and restore, specifically so an upgraded v1 blob
  is migrated to v2 on disk on first load (verified: `v:1 → v:2` after one reload) rather than
  re-upgraded every reload. Safe — it writes exactly what was just put in memory for the current uuid.
- **ℹ️ One-way `:layout` bind, not `v-model`.** The library mutates the bound array in place and re-syncs
  only when the array **reference** or **length** changes; a one-way bind + `@layout-updated` commit +
  debounced deep-watch persist captures every gesture without a write-back loop, and switching pages
  (reference swap) / adding a tile (length change) correctly re-renders while an in-place drag does not
  reset.
- **🟢 Interactivity guard is a whitelist.** `drag-allow-from=".tile-drag-handle"` alone protects every
  non-grip element; no `drag-ignore-from` (which would have to exclude `js-export-exclude`, breaking the
  grip). Verified: all in-tile `<select>`/buttons remained clickable during state edits.
- **🟢 Layout self-heals.** `reconcilePageLayout` drops orphan layout items and appends any tile missing
  one at the bottom, so a hand-edited/partial blob always renders every tile exactly once; normally a
  no-op since add/remove keep `layout` in lockstep.
- **🟢 Cross-filter is per-view.** Switching or deleting the active page clears the slice and refetches,
  so a stale filter can't carry across pages; a `dataVersion` bump that drops the filtered column also
  clears it (unchanged from before).
- **🟢 Back-compat / persistence.** Deep-watch persist is debounced (~250ms) so a drag coalesces to one
  write; `persistNow()` on gesture-end survives an immediate reload; all writes are per-user namespaced
  and quota-swallowing. A v1 board upgrades losslessly (configs + titles preserved).
- **ℹ️ Verification mutated the live `uid=7` demo board**, then reset it to a pristine seed (confirmed).
