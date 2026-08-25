# TASK-032 — Wave 6b: Export dashboard (PNG / PDF) + present/fullscreen (#17)

**Status: IN PROGRESS** (do not self-close)

## Objective
Backlog **#17 — "Export dashboard PNG/PDF; present/fullscreen"**. Today only *per-tile* PNG exists
(`ChartTile.exportPng` → ECharts `getDataURL()`); there is no way to capture the **whole board** (KPI
cards + charts + layout) or show it clean for a stakeholder. This adds three Canvas-level actions:

1. **Export dashboard as PNG** — one image of the entire board.
2. **Export dashboard as PDF** — that image on a single page sized 1:1 to it.
3. **Present / fullscreen** — the board fullscreen with all editing chrome hidden (Esc to exit).

## Approach & why
- **Rasteriser = `html-to-image` (`toPng`).** It serialises the DOM into an SVG `<foreignObject>` and
  lets the **browser** paint it, so two repo-specific hazards are handled for free: (a) the design
  tokens compute to **oklch** colours (which `html2canvas` cannot parse), and (b) each ChartTile plot is
  an ECharts `<canvas>` (whose pixels `html-to-image` reads via `toDataURL`). A single rasterisation
  therefore captures DOM/SVG KPI cards **and** canvas charts together.
- **PDF = `jspdf` (`addImage`).** The PDF is just the PNG on one page whose format = the image's pixel
  size, so it fills the page 1:1 with no reflow. One rasterisation feeds both encoders. jspdf pinned to
  **4.2.1** (the line that drops the vulnerable transitive DOMPurify — `npm audit` is **0
  vulnerabilities**; our `addImage` path never touches jspdf's `.html()`/DOMPurify code anyway).
- **Clean capture = one `js-export-exclude` contract.** Editing chrome is tagged with that class:
  the Canvas header action bar, the two dashed "Add KPI/Add chart" buttons, the transient export-error
  strip, and **each ChartTile's control strip** (pickers + per-tile action buttons) — but **not** the
  tile `<h3>` titles or the KPI-card titles, which stay so the export is labelled. The PNG `filter`
  drops every `.js-export-exclude` node; the **same** class is hidden in present mode by one scoped
  `.dashboard-clean :deep(.js-export-exclude){display:none}` rule. Both views therefore render the
  identical clean board. (Hiding the native `<select>` pickers also sidesteps the known
  `foreignObject` form-control rendering quirk.)
- **Present = the Fullscreen API** on the capture root. `requestFullscreen()`/`exitFullscreen()`;
  `document.fullscreenchange` drives `presenting`, so pressing **Esc** correctly restores the editing
  view. In fullscreen the root gets a solid `bg-surface-base` + padding + scroll (a bare element would
  paint on black).

## What changed
### Frontend (only) — no backend, no wire contract, no new config/secret
- **`components/ChartCanvas.vue`**
  - Imports `toPng` (html-to-image), `jsPDF` (jspdf), `onMounted`/`onBeforeUnmount`, and the
    `ImageDown`/`FileDown`/`Maximize` icons.
  - New state: `captureEl` (ref on the board root), `presenting`, `exporting: ''|'png'|'pdf'`,
    `exportError`; `hasTiles` computed (gates the actions when the board is empty).
  - `exportImage('png'|'pdf')` — rasterise via `snapshot()` (`pixelRatio 2`, `skipFonts:true`, `cacheBust`,
    `backgroundColor` resolved by walking up to the first non-transparent ancestor, `filter` drops
    `js-export-exclude`) wrapped in a **`Promise.race` 20 s timeout** so a stalled rasterise rejects instead
    of hanging; then download the PNG or wrap it in a 1:1 jsPDF page. Errors surface in a dismissible strip;
    never throws to the UI and never leaves the buttons wedged.
  - `togglePresent()` + `syncPresenting()` on `fullscreenchange` (added/removed in mount/unmount).
  - Template: `ref="captureEl"` on the board root, which gains `dashboard-clean bg-surface-base p-4
    overflow-auto` only while `presenting`. Three buttons (Present / PNG / PDF) added to the header,
    which now carries `js-export-exclude`; the two add-buttons and the error strip carry it too. A
    scoped `<style>` block adds the single `.dashboard-clean` hide rule.
- **`components/ChartTile.vue`** — the header **control strip** div (dimension/breakdown/measure/agg/
  type pickers + recommend/explain/download/remove buttons) gains `js-export-exclude`. The tile `<h3>`
  title is a sibling and is untouched, so exported/presented tiles keep their titles.

### Dependencies
- `html-to-image@^1.11.x` and `jspdf@^4.2.1` added to `frontend/package.json`. `npm audit` → 0 vulns.

## Config
**None.** No env vars, no secrets, no client-controlled server surface.

## Acceptance criteria
1. 🟨 **Dashboard PNG.** *(Deferred to real-browser check — see Verification.)* Code path produces a
   whole-board PNG via the bundled `toPng` at `pixelRatio 2`; not verifiable in the 0×0 headless preview
   (html-to-image does not resolve here). Browser raster **primitive** proven working in-env.
2. 🟨 **Dashboard PDF.** *(Deferred with AC1.)* `jsPDF.addImage` wraps the PNG on a single page sized 1:1
   to it; blocked in-env only because AC1's raster can't complete here.
3. ✅/🟨 **Clean capture.** Structurally proven: exactly the 4 chrome nodes carry `js-export-exclude`
   (header actions, both add-buttons, per-tile control strip); tile/KPI **titles** are NOT excluded. The
   pixel-level filter result rides on AC1 (deferred).
4. ✅/🟨 **Present/fullscreen.** The `dashboard-clean` class present mode toggles is proven to hide all
   chrome (`display:none`) and keep titles, reversibly. Real OS `requestFullscreen` is user-gesture-gated
   → the actual enter/exit + Esc is the user's real-browser check.
5. ✅ **Empty-board + in-flight + failure guards.** Disabled when no tiles; a 2nd export is ignored while
   one runs; a hung/failed rasterise trips the 20 s timeout → error strip → buttons re-enable (no wedge).
6. ✅ **Strict build green.** `vue-tsc -b && vite build` clean (twice).
7. ✅ **Must-not-change:** `README.md`, `.ai/CURRENT_STATE.md` untouched; footprint = `ChartCanvas.vue`,
   `ChartTile.vue`, `package.json`/`package-lock.json` (+ this spec).

## Verification (real output)
**Environment:** real Redis (portable `redis-server.exe`), backend `:8000`, Vite preview `:5173`,
authenticated as `kpitest@example.com`, `spark_demo.csv` on `/canvas` (seeded KPI cards + one chart tile
"Sum of revenue by region"). The headless preview viewport is **0×0**, so proof is DOM/`getComputedStyle`/
byte-decode based (screenshots unavailable).

- **AC6 — strict build.** `vue-tsc -b && vite build` → `✓ built` twice (after wiring, and after the
  `snapshot()` hardening). Only the pre-existing >500 kB chunk advisory. jsPDF's `.html()`-only transitive
  deps (`purify.es` = DOMPurify, `html2canvas`) are code-split into **separate lazy chunks** the `addImage`
  path never loads — which is why `npm audit` stays **0 vulnerabilities**.
- **AC7 — footprint.** `git status`: this task touched only `ChartCanvas.vue`, `ChartTile.vue` (a 1-line
  class add), `package.json`/`package-lock.json` (+ this spec). `README.md` and `.ai/CURRENT_STATE.md` are
  **not** in the change set. (Other modified files in the tree belong to already-signed-off
  TASK-029/030/031 awaiting commit.)
- **Wiring/DOM (AC3 structural).** On `/canvas`: Present/PNG/PDF buttons render with correct titles;
  disabled logic observed (enabled with tiles; PDF gated while a PNG export is mid-flight). `captureEl` ref
  present on the board root. Exactly **4** `.js-export-exclude` nodes = header action bar + Add KPI + Add
  chart + the tile's control strip; the tile `<h3>` "Sum of revenue by region" is **not** inside any
  excluded node (titles preserved). Scoped rule compiled to
  `.dashboard-clean[data-v-1174089b] .js-export-exclude { display:none !important }`.
- **AC4 — present-mode contract.** Adding `dashboard-clean` to the root (exactly what `togglePresent` +
  `syncPresenting` toggle via `presenting`) made chrome compute `display:none`, kept the tile title
  `display:flex`, and reverted to `flex` on removal. Programmatic `root.requestFullscreen()` →
  `TypeError: Permissions check failed` (gesture-gated) → **real fullscreen enter/exit + Esc is the user's
  check**.
- **AC5 — guards (fully proven, incl. the failure path).** Buttons `:disabled` when `!hasTiles`; a 2nd
  export no-ops while `exporting` is truthy. Driving the **real** whole-board "PNG" button made
  html-to-image **hang** (see env note); the new **20 s timeout** then rejected → caught → the strip showed
  *"Export timed out — the dashboard may be too large or a resource failed to load."* and **both buttons
  re-enabled** — the UI did **not** wedge. (Before the timeout, a *hang* — not a rejection — left the
  buttons permanently disabled; found and fixed during review.)
- **AC1/AC2 + pixel-AC3 — NOT verifiable in this env → user's real-browser check (pre-agreed).**
  html-to-image's `toPng` does **not** resolve in this 0×0 headless renderer for *any* node: confirmed by
  (a) the real buttons hanging until the timeout, and (b) importing the app's **own bundled** `toPng`/`jsPDF`
  and rasterising a small synthetic node with the exact `exportImage` options — still timed out at 8 s,
  **even after test-detaching the cross-origin `fonts.googleapis.com` link**. The browser's underlying
  primitive works, though: a hand-built `<foreignObject>` SVG → `<img>` → `<canvas>` → `toDataURL('image/png')`
  produced a valid `data:image/png` (signature `89 50 4e 47 0d 0a 1a 0a`), proving the mechanism
  html-to-image relies on is supported here — only the library's clone→inline→img-load chain won't complete
  under 0-px layout. **User's single real-browser confirmation:** open `/canvas` with a dataset, click PNG
  then PDF → both download and open (PNG of the whole board minus chrome; PDF one page, 1:1); click Present
  → clean fullscreen, Esc restores. In a normal browser `toPng` completes in ms.

## Definition of Done
The Canvas can export the whole board to PNG and to a 1:1 PDF and enter a clean fullscreen present mode,
with editing chrome excluded from both via one `js-export-exclude` contract, titles preserved, empty/
in-flight/error paths guarded; strict build clean; must-not-change verified. Left in `tasks/active/` for
the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
No open 🔴/🟠. One 🟠 was **found and fixed** during review; two 🟡 judgment calls (both flagged, not
silent); the rest ℹ️.

- 🟠→🟢 **No-timeout wedge (found & fixed during review).** The first live whole-board export left
  `exporting` stuck truthy → **both buttons permanently disabled**, directly contradicting AC5's "never
  wedges." Root cause: html-to-image's clone→CSS-inline→`<img>`-load chain never *resolves* (a **hang**,
  not a rejection) under the 0-px headless layout, so the `.catch()` never ran. Fix: wrapped `snapshot()`
  in `Promise.race([toPng(...), 20 s timeout])` so a stalled rasterise **rejects** → caught → error strip
  → `exporting=''` → buttons re-enable. Proven live end-to-end (strip text + both buttons re-enabled). A
  real browser resolves in ms and never trips it; the timeout is a pure safety net.
- 🟡 **`skipFonts: true` trade-off.** Set to make the raster robust and fast (no cross-origin webfont CSS
  fetch/inline, which also threw a caught `SecurityError` on the `fonts.googleapis.com` sheet in-env). The
  cost is that html-to-image won't embed webfont bytes — but the board's numerals/labels use **Inter**,
  already loaded locally, so the browser paints the identical face. Net: no fidelity loss on this app; a
  deployment that swaps in an exotic *webfont-only* face would want to revisit. Reversible one-liner.
  **Recommendation: keep.**
- 🟡 **`pixelRatio: 2` on very large boards.** Doubling raster resolution keeps text crisp and PDFs sharp,
  but a huge board (many tiles) rasterised at 2× is memory-heavy and could OOM the tab. Not observed in-env
  (can't complete the raster here at all), and if it *did* fail it now degrades cleanly: the error is caught,
  the strip explains "the dashboard may be too large…", and the UI recovers (no wedge, per the fix above).
  A future adaptive ratio (scale down past N tiles) is a reasonable follow-on. **Recommendation: keep 2×**
  for demo-scale boards; note the guard is what makes it safe.
- ℹ️ **`cacheBust: true`.** Appends a cache-buster when html-to-image re-fetches referenced resources, so a
  stale/`no-cors` opaque cache entry can't poison the raster. Negligible cost on a one-shot user action.
- ℹ️ **Env limitation is not a defect.** AC1/AC2 blob-validity + pixel content are un-capturable **only**
  because this preview renders at 0×0 (html-to-image needs real layout). I proved the browser's *underlying*
  primitive (`<foreignObject>` SVG → `<img>` → `<canvas>` → PNG) works here and that the app's own bundled
  `toPng` is the piece that stalls under 0-px — so the deferral is honest and narrowly scoped to the two
  pixel-output ACs, which are the user's single real-browser check (pre-agreed split).
- ℹ️ **Footprint clean.** Only `ChartCanvas.vue`, `ChartTile.vue` (1-line class), `package.json`/
  `package-lock.json`, and this spec. `README.md` / `.ai/CURRENT_STATE.md` untouched; `npm audit` 0 vulns;
  jsPDF's DOMPurify/html2canvas transitive deps are lazy chunks the `addImage` path never loads. No backend,
  no wire-contract, no config/secret.
