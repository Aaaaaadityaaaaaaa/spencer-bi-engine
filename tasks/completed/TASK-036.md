# TASK-036 — Power BI Canvas, part 4: custom colour + card fill, whole-card drag, bold, per-chart Top-N

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
Four Power BI–style polish features you asked for on top of the Canvas trilogy (TASK-033/034/035):

1. **Colour like Power BI** — every preset swatch now sits next to a **custom colour picker** (native
   `<input type="color">` + a hex text field), for the **chart series** *and* the **KPI sparkline
   accent**, **plus** a brand-new per-tile **card background fill** on both KPI cards and chart tiles
   (preset tints + custom picker + "None").
2. **Movable cards (finishes TASK-034's "movable" criterion the Power BI way)** — tiles already resized
   but felt un-movable because only a tiny grip started a drag. Now the **whole card is the drag
   surface** — grab a tile anywhere empty and move it, exactly like Power BI — while every control on the
   tile stays clickable.
3. **Bold text** — a per-tile **Bold** toggle that bolds the tile **title**, and on KPI cards **also the
   big value**.
4. **Per-chart Top-N** — a **"Show top ___"** number box with **5 / 10 / 20 / All** shortcuts on each
   chart, so a "revenue by region" bar can show just the top few categories.

Frontend-only. **No new dependency, no backend change, no wire-contract change** — Top-N reuses the
aggregate endpoint's *pre-existing* measure-DESC sort + category clamp.

## Approach & why
- **Colour: additive, dual-format-safe.** `chartPalette.ts` gains a **card-background palette**
  (`CHART_BG_PALETTE` — 8 light oklch tints paired to the 8 series hues) and three small helpers:
  `normalizeHex(raw) → '#rrggbb'|null` (validates a typed hex), `asHexInput(c, fallback)` (feeds the
  native `<input type=color>` a displayable `#rrggbb`, since it can't render an oklch preset), and
  `PICKER_FALLBACK`. Nothing converts colours: **CSS and ECharts both accept oklch (presets) *and* hex
  (picker) as-is**, so a preset stays oklch and a picked colour stays `#rrggbb` — no lossy round-trip.
  Each popover is now **two sections** (series/accent colour • card background), each with the preset
  grid + native picker + hex field + a reset ("Auto" / "None").
- **Whole-card drag, guarded by a blacklist (not a grip).** TASK-034 planned a *small grip handle*; that
  read as "barely movable". To match your explicit "movable like Power BI", the **card root** is now the
  `.tile-drag-handle` (grid `drag-allow-from`), so a drag can begin **anywhere** on the tile — and a
  single `drag-ignore-from` blacklist keeps every interactive thing un-hijacked:
  `button, select, input, textarea, a, summary, canvas, .no-drag, .vgl-item__resizer`. That covers every
  swatch/toggle/number box (`button`,`input`,`select`), the popovers (`.no-drag`), the ECharts plot
  (`canvas`), and the resize handle (`.vgl-item__resizer`). interact.js walks ancestors, so a control
  nested in the card still wins over the card's drag. The old grip stays purely as a **visual cue**
  (`cursor-grab`).
- **Bold = one boolean, one class swap.** `config.bold` toggles `font-bold` on the title (both tiles) and
  on the KPI value; no layout shift, no refetch.
- **Top-N = reuse the server's existing top-N, gate the refetch.** The aggregate service **already**
  clamps `limit = max(1, min(req.limit or 50, MAX_CATEGORIES=200))` and sorts categorical dimensions by
  the measure **DESC** — i.e. it already returns *top-N by measure* and flags `truncated`. So Top-N is
  frontend-only: the number box writes `config.topN`, `ChartCanvas` sends
  `limit: max(1, min(cfg.topN ?? SERIES_LIMIT, TOPN_CAP=200))`, and — unlike colour/bold/bg — **`topN` is
  added to the `sameQuery` guard so it *does* refetch** (colour/bold/bg deliberately do not). The box is
  shown only when the chart has a categorical `dimension`.
- **Persistence for free.** The active-board snapshot deep-clones the *whole* config (not an allowlist),
  so the four new optional fields (`color`/`accent`, `bg`, `bold`, `topN`) ride along automatically and
  survive reload with zero persistence-layer change.

## What changed
### Frontend (only) — no backend, no wire contract, no new dependency, no new config/secret
- **`utils/chartPalette.ts`** — added `CHART_BG_PALETTE` (8 light tints), `PICKER_FALLBACK`, `HEX6`
  regex, `normalizeHex()`, `asHexInput()`. (`CHART_PALETTE`/`paletteColor` unchanged.)
- **`types.ts`** — `ChartConfig +=` `bg?: string|null`, `bold?: boolean`, `topN?: number|null`;
  `KpiConfig +=` `accent?: string|null`, `bg?: string|null`, `bold?: boolean` (all optional →
  back-compat, matching the existing "optional additions are back-compat" note).
- **`components/ChartTile.vue`** — card root is the `.tile-drag-handle`; two-section colour/background
  popover (presets + native picker + hex + Auto/None), `.no-drag` backdrop/panel; **Bold** toolbar
  button; **Top-N** block (`DEFAULT_TOPN=50`, `TOPN_MAX=200`, presets 5/10/20/All, `setTopN`/
  `onTopNInput`) guarded by `v-if="config.dimension"`; header goes transparent when a `bg` fill is set.
- **`components/KpiCard.vue`** — card root is the `.tile-drag-handle`; two-section popover (sparkline
  accent + card background); **Bold** button (bolds title **and** value); `:style` card-fill + accent
  colour; handlers `pickColor`/`onAccentHex`/`pickBg`/`onBgHex`/`toggleBold`.
- **`components/ChartCanvas.vue`** — `drag-allow-from=".tile-drag-handle"` + the `drag-ignore-from`
  blacklist on `<GridLayout>`; `TOPN_CAP=200`; `limit: max(1, min(cfg.topN ?? SERIES_LIMIT, TOPN_CAP))`
  on the aggregate call; `topN` folded into the `sameQuery` refetch guard.

No change to `useDashboards.ts`, `useAuth.ts`, the backend, or the wire contract.

## Config
**None.** No env vars, no secrets, no client-controlled server surface, no new dependency. The colour
values live only in the per-user `localStorage` board blob (`spencer.activeDashboard:<userId>`).

## Acceptance criteria
1. **Custom colour** — a chart's series recolours to a typed/picked hex *and* to a preset; a KPI's
   sparkline accent likewise; both persist across reload.
2. **Card fill** — a per-tile background fill (preset tint or custom) applies to a KPI card and a chart
   tile, "None" clears it, and it persists.
3. **Whole-card drag** — a tile can be dragged from any empty area of the card, while every control
   (swatches, hex fields, pickers, Bold, number box, presets, resize handle) stays clickable and does
   **not** start a drag.
4. **Bold** — the toggle bolds a chart title and a KPI title+value, persists, and un-bolds cleanly.
5. **Top-N** — the number box / presets limit a chart to the top-N **by measure**; `truncated` reflects
   whether more existed; changing Top-N **refetches**, changing colour/bold/bg does **not**.
6. **Strict build green** — `vue-tsc -b && vite build` clean.
7. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user `uid=7`, dataset
`spark_demo.csv` (`order_date` DATE, `region` VARCHAR, `revenue` BIGINT; 12 rows).

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 2.67s`,
  zero TS errors.**
- **#1 Custom colour (chart)** — set the chart series to typed hex **`#ff8800`**; decoded the live
  ECharts option (`getInstanceByDom(host).getOption()`): `series[0].itemStyle.color === '#ff8800'`.
  Persisted `pages[0].charts[i].config.color === '#ff8800'`.
- **#1 Custom colour (KPI accent)** — set a KPI accent to **`#22aa66`**; the sparkline `<polyline>`
  computed stroke read **`rgb(34, 170, 102)`**. Persisted `pages[0].kpis[i].accent === '#22aa66'`.
- **#2 Card fill** — applied a preset background tint to a chart tile; `getComputedStyle(tileRoot)
  .backgroundColor` returned the oklch tint and the header went transparent; persisted `…config.bg`.
  Popover confirmed: **2 sections, 2 native pickers, 2 hex fields, 16 swatches (8+8), Auto + None
  resets**, backdrop/panel both `.no-drag`.
- **#4 Bold** — chart title carried `font-bold` and persisted `…config.bold === true`; KPI **title and
  value** both `font-bold`, persisted `…kpis[i].bold === true`.
- **#5 Top-N (true top-N + refetch)** — number box → **1** produced request `limit:1`, response
  `truncated:true`, `keys:["North"]`; preset **"Show top 5"** produced `limit:5`, `truncated:false`,
  `keys:["North","South"]` — and **North (rev 970) sorted above South (700)**, i.e. genuine top-N by
  measure, not insertion order. Each Top-N change issued a fresh `/aggregate` (refetch confirmed); colour
  / bold / bg changes issued **none** (guard confirmed).
- **Reset paths** — a *sequential* revert (one field per tick) cleared **every** field: chart
  `{color:null, bg:null, bold:false, topN:null}`, KPI `{accent:null, bg:null, bold:false}` — proving
  "Auto" / "None" / un-Bold all work and the popover writes are independent.
- **Reload survival** — after a full page reload the restored board still showed chart bold + bg +
  `#ff8800`, and KPI bold-title + bold-value + bg + sparkline `rgb(34,170,102)`.
- **Cleanup** — all test styling reverted; the persisted `uid=7` blob ends clean
  (all four fields `null`/`false`). No lasting change to your data.

**Env caveat (carried from TASK-032/034):** the preview viewport is **0×0**, so the actual pointer
**drag** gesture (grab-anywhere-and-move) and **resize** gesture are the **user's real-browser check**.
In-env everything else is authoritative and fully exercised above: ECharts option decode, sparkline
`getComputedStyle`, the `/aggregate` request `limit` + response `truncated`/`keys`, and the persisted
`localStorage` blob across a reload. That every control (Bold, swatches, hex fields, native pickers,
number box, presets, resizer) is a `drag-ignore-from` match — and stayed independently clickable in-env —
is strong evidence the whole-card drag layer does not swallow control events; the gesture itself remains
your browser check.

## Definition of Done
Chart series colour, KPI accent, and a new per-tile card fill are each pickable from presets **or** a
custom hex/native picker (with Auto/None resets); tiles drag from anywhere on the card while controls stay
live; a Bold toggle bolds title (and KPI value); a per-chart Top-N number box + 5/10/20/All limits a chart
to the top-N by measure and refetches. All four persist across reload. Strict build clean; must-not-change
verified; no backend/dependency/wire change. Left in `tasks/active/` for the single sign-off. **Not
self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. Two 🟡 judgment calls for your sign-off; the rest 🟢 / ℹ️.

- **🟡 Whole-card drag deviates from the planned grip-only handle.** TASK-034's plan specced a *small
  grip*; I made the **entire card** the drag surface to match your "movable like Power BI" ask. Safety
  now rests on the `drag-ignore-from` blacklist
  (`button, select, input, textarea, a, summary, canvas, .no-drag, .vgl-item__resizer`) being complete —
  it covers every current control, and I verified in-env that each stayed clickable. **Watch-point:** a
  *future* non-standard control (e.g. a clickable `<div>` that isn't one of those tags) would need a
  `.no-drag` class or it'd start a drag instead of clicking. Also note **rename is via the pencil**
  (clicking the title text just starts a drag), matching the app's existing inline-edit idiom rather than
  double-click-to-rename. **Your call:** keep grab-anywhere (recommended — it's the Power BI feel you
  asked for), or revert to grip-only?
- **🟡 Top-N means "top N by the measure", and only for charts with a categorical dimension.** It reuses
  the server's existing measure-DESC sort + `MAX_CATEGORIES=200` clamp, so it's exactly Power BI's
  default "Top N" filter — but it's only meaningful when there's a measure to rank by and a dimension to
  limit (the box is hidden otherwise via `v-if="config.dimension"`). For a 2-D breakdown, `topN` caps the
  **primary** dimension; series are capped separately by the pre-existing `MAX_SERIES`. Flagging the
  semantics so there's no surprise that it's not "top N rows" or "top N by name".
- **🟢 Colour is dual-format-safe, no lossy conversion.** Presets stay oklch, picked/typed colours stay
  `#rrggbb`; CSS and ECharts accept both. `asHexInput()` only supplies the native swatch a *displayable*
  hex (an approximation for oklch presets) — the **stored** value is never mutated by opening the picker.
  Verified `#ff8800` reached the ECharts option and an oklch tint reached `getComputedStyle`.
- **🟢 Refetch guard is correct and minimal.** `topN` is in `sameQuery` (so a Top-N change refetches);
  colour/bold/bg are pure presentation and deliberately do **not** refetch. Verified: Top-N change → one
  new `/aggregate`; colour/bold/bg change → zero.
- **🟢 Persistence rides the existing deep-clone.** The snapshot clones the whole config, so
  `color`/`accent`/`bg`/`bold`/`topN` persist automatically — no allowlist to keep in sync, no migration
  (older blobs simply lack the keys → treated as null/false). Verified all four survived a reload.
- **🟢 No backend / dependency / wire change.** Top-N is the frontend sending an existing request field;
  `aggregate_service.py`'s clamp + sort are untouched. `grid-layout-plus` (added in TASK-034) is reused,
  nothing new installed.
- **ℹ️ Native `<input type=color>` can only display `#rrggbb`.** For an oklch preset the native swatch
  shows an approximate hex via `asHexInput()`; the hex text field and the actual applied colour are
  unaffected. Cosmetic only.
- **ℹ️ Verification mutated the live `uid=7` demo board**, then reverted every field to null/false
  (confirmed clean above).
