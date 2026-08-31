# TASK-008

## Title
Frappe-Insights-inspired UI restyle — design-token foundation (light-only)

## Objective
Replace the Vite-scaffold look (single indigo accent, default Tailwind grays, `<title>frontend</title>`,
dead nav) with a coherent design system mirroring **Frappe UI's** visual language: CSS-variable
semantic tokens (surface / ink / outline / primary + red/green/amber), a numbered radius scale,
multi-layer elevation shadows, the Inter typeface, and the authentic lucide icon set. Restyle the
existing shell and all five visible components **in place** — no restructure, no routing, no new
features, no new backend calls. Preserve every TASK-006 behavior (Axios wiring + the virtualized
grid). Backend untouched.

## Context
Spencer's frontend is functionally live through TASK-006 (upload → schema pills → virtualized,
infinite-scrolling grid, wired to `POST /sessions` and `GET /sessions/{id}/data`) but still wears the
scaffold's appearance. The user asked for a UI **inspired by Frappe Insights**, which shares Spencer's
exact stack (Vue 3 + Tailwind + DuckDB + Ibis + ECharts). Direction locked over two AskUserQuestion
rounds plus the plan approval this session:

- **Mirror Frappe UI's semantic tokens in Spencer's own Tailwind config** — do NOT depend on the
  `frappe-ui` npm package.
- **Token layer = CSS variables** (Frappe's own mechanism), so light/dark/auto becomes a later
  one-class flip. **This task ships light-only** (`[data-theme="dark"]` block wired but empty).
- **Icons = lucide** (the authentic Frappe set, tree-shakeable) — one new runtime dep.
- **Structure = session-as-workbook, tabs later** → **restyle in place**, not a restructure.
- **First build = restyle the current UI** (shell + all visible components) for visible, low-risk progress.

**Scope boundary (AP-2):** visual only. No component gains new behavior; the AI box / chart canvas /
custom-instructions remain static shells (reskinned only). The one new *interactive* affordance is a
sidebar collapse toggle — a layout nicety, not product behavior. Backend is untouched. Token values
below are the **real Frappe UI values** pulled from `frappe-ui/tailwind` source (achromatic neutrals in
`oklch`, blue accent, numbered radii, multi-layer elevation). Vite 8 targets modern browsers, so
`oklch()` is safe. Grid v2 (server-side sort, type-aware cells) remains earmarked as TASK-007 — this
restyle does not consume it.

## Requirements
1. **Token foundation** — `frontend/src/style.css`: add a `:root` CSS-variable layer (surface, ink,
   outline, primary, semantic red/green/amber, `--radius-1..7`, `--elevation-sm/base/md`, `--focus-ring`)
   plus an empty `[data-theme="dark"]` block and an `@layer base` html default (Inter font, ink-gray-8
   text, surface-gray-1 background, antialiasing). Keep the three `@tailwind` directives.
2. **Token → utility mapping** — `frontend/tailwind.config.js`: `darkMode: ['selector', '[data-theme="dark"]']`;
   `theme.extend.colors` maps `surface/ink/outline/primary` (+ red/green/amber) to the `var(--…)` tokens;
   `borderColor.DEFAULT`, `borderRadius` 1..7, `boxShadow` sm/DEFAULT/md, `fontFamily.sans` = Inter stack.
   Extend (not replace) — Tailwind's default palette stays available so nothing breaks mid-migration.
3. **`frontend/index.html`**: `<title>Spencer</title>`; preconnect + Inter stylesheet (weights 400;500;600).
4. **Icons**: one new runtime dep (lucide); per-component imports; icons where intent already exists —
   `Upload`/`Loader2` (dropzone), `Sparkles` (AI box), `BarChart3` (chart), `Plus`/`Trash2` (instructions),
   `Loader2` (grid loading), plus shell icons `Table`/`CalendarClock`/`Settings`/`PanelLeft(Close)`/`Undo2`/`Redo2`.
5. **Shell** — `frontend/src/App.vue`: keep the sidebar+header+content skeleton; swap to the token
   vocabulary; collapsible sidebar (`w-60 ↔ w-16`, `collapsed` ref) with brand mark + wordmark, three
   **inert** nav items (no router yet), and a collapse toggle; header title + **inert** disabled-styled
   Undo/Redo icon buttons (matching today's no-op behavior).
6. **Components** — apply one consistent card/button/form/muted-text/error vocabulary across
   `UploadDropzone`, `DataGrid`, `AIQueryBox`, `ChartCanvas`, `CustomInstructions`. **Colors/icons only.**
7. **DataGrid guardrails (load-bearing):** change colors only. Preserve `PAGE=500`, `ROW_H=36`,
   `COL_W=160`, `ref="scrollEl"`, `style="height: 440px"`, `translateY` absolute row positioning, the
   `px-3 py-2` cell padding (row height must stay 36px or `estimateSize` desyncs), and the
   `useSession()` destructure `{ sessionUuid, tableName }`. UploadDropzone: preserve the hidden
   `<input>`, drag/drop handlers, and `{ columns, rowCount, uploading, error, sessionUuid, upload }`.
8. `npm run build` must pass strict `vue-tsc` (`noUnusedLocals`/`noUnusedParameters` ON → every imported
   icon and every `ref` must be used).

## Files Expected To Change (frontend only)
- `frontend/src/style.css` — CSS-variable token layer + base defaults.
- `frontend/tailwind.config.js` — token→utility mapping, darkMode selector, radius/shadow/font.
- `frontend/index.html` — `<title>Spencer</title>` + Inter (Google Fonts).
- `frontend/package.json` (+ `package-lock.json`) — add the lucide runtime dep.
- `frontend/src/App.vue` — restyled shell + collapsible sidebar.
- `frontend/src/components/{UploadDropzone,DataGrid,AIQueryBox,ChartCanvas,CustomInstructions}.vue` —
  reskinned to the token vocabulary; behavior unchanged.

## Files That Must NOT Change
- **All of `backend/`** — this is a frontend-only visual task. In particular
  `backend/services/duckdb_manager.py` (frozen since TASK-001-FIX-02/TASK-002) is untouched.
- **Logic layer**: `frontend/src/services/api.ts`, `frontend/src/composables/useSession.ts`,
  `frontend/src/types.ts`, `frontend/src/main.ts` — pure logic / no styling; not touched.
- `frontend/src/components/HelloWorld.vue` — already dead/unused; left as-is and flagged for a future
  cleanup task (AP-2 — noted, not silently dropped).

## Security Considerations (AP-8 — name the exact path each control covers)
Visual-only change; it introduces **no new backend call, no new SQL, and no new user-input path**.
- The AI query box, chart canvas, and custom-instructions remain **static shells** — no SQL is
  constructed or executed by this task; the AI-SQL path (`run_sandboxed` + sqlglot validator) is not
  wired here and is unchanged.
- The only new **external** dependency is Google Fonts (`fonts.googleapis.com` stylesheet +
  `fonts.gstatic.com` woff2). It carries `crossorigin` on the gstatic preconnect; if the CDN is
  unreachable the Inter stack **degrades gracefully** to `ui-sans-serif, system-ui, sans-serif`
  (verified: the `font-family` cascade is authored with those fallbacks). Self-hosting Inter to drop the
  third-party dependency is a candidate follow-up (Self-Review finding 4).
- lucide icons are inline SVG components (no runtime network fetch, no `<img src>` to a CDN).
- No secrets, tokens, or env values are added to client code.

## Acceptance Criteria
1. **Token pipeline resolves:** computed styles on real elements equal the authored `oklch` token
   values; Inter is the rendered font.
2. **Strict build clean:** `npm run build` (`vue-tsc -b && vite build`) passes with
   `noUnusedLocals`/`noUnusedParameters` on — proving no stray icon/ref imports.
3. **Functional regression intact:** upload → schema pills → grid first window; scrolling fires a
   **second `/data` window at `offset=500`** and appends rows (virtualizer survived the restyle);
   console application-clean.
4. **Shell:** collapsible sidebar toggles `w-60 ↔ w-16` (label + wordmark hide when collapsed); brand,
   three inert nav items, and inert Undo/Redo render.
5. **All five components** reskinned to the shared token vocabulary; DataGrid guardrails preserved
   (row height 36px, scroll container, `useSession` bindings).
6. **Scope:** `git status` shows only the expected `frontend/**` files; `git diff -- backend/` empty.

## Definition Of Done
All acceptance criteria shown as real output; frontend-only with the entire backend (and
`duckdb_manager.py`) unchanged; all TASK-006 wiring/behavior preserved; self-review with severity grades
attached. **Sign-off is the user's — I do not self-close this task.**

## Status
COMPLETE — **awaiting user sign-off** (not self-closed).

Proof: fresh in-session evidence — strict `vue-tsc` build clean (§A); computed token values resolve to
the authored `oklch` (§B); shell structure + all five reskinned cards present (§C); collapse toggle
`w-60/240px ↔ w-16/64px` with labels hiding (§D); frontend-only scope with backend diff empty (§F).
Functional regression (upload → grid → `offset=500` second window, virtualization intact) was proven in
the prior verification run with the backend **up** (§E) — see the honesty note there; it was **not**
re-run this session because only Vite was restarted (backend intentionally down). Self-Review records
one plan deviation (lucide package name) and the headless-screenshot limitation.

## Proof

Fresh evidence (§A–§D, §F) was captured **this session** via `preview_*` MCP tools against Vite on
`:5173` (the shell renders without a backend). §E is the functional regression captured in the prior
verification run when Redis + backend were live; it is labelled as such and not restated as fresh.

### A. Build — strict `vue-tsc` (AC2) — fresh
`npm run build` (= `vue-tsc -b && vite build`), current run:
```
> frontend@0.0.0 build
> vue-tsc -b && vite build
vite v8.2.1 building client environment for production...
✓ 1868 modules transformed.
dist/index.html                   0.74 kB │ gzip:  0.39 kB
dist/assets/index-BwDabfFi.css   11.73 kB │ gzip:  3.47 kB
dist/assets/index-B1vgss9h.js   150.19 kB │ gzip: 54.08 kB
✓ built in 21.74s
```
`vue-tsc -b` runs first and passed — under `noUnusedLocals`/`noUnusedParameters` this proves every
imported lucide icon and every `ref` is used (an unused import fails the build). (The rolldown
`[PLUGIN_TIMINGS]` line is a performance note on the HTML transform, not an error.)

### B. Token pipeline — computed styles resolve to authored `oklch` (AC1) — fresh
`preview_inspect` / `preview_eval` computed values on live elements:
```
aside   background-color   oklch(0.979 0 0)               = --surface-gray-1   ✓
aside   border-right-color oklch(0.946 0 0)               = --outline-gray-1   ✓
aside   font-family        Inter, ui-sans-serif, system-ui, sans-serif         ✓ (Inter loaded)
header  background-color   oklch(1 0 0)                   = --surface-base     ✓
header  border-bottom-color oklch(0.946 0 0)              = --outline-gray-1   ✓
header  color              oklch(0.205 0 0)               = --ink-gray-8       ✓
brand mark  background-color   oklch(0.587 0.174 252.167) = --primary-6        ✓
"Ask" button background-color  oklch(0.587 0.174 252.167) = --primary-6        ✓ (Frappe blue)
```
End-to-end pipeline confirmed: CSS variable → Tailwind `theme.extend.colors` mapping → utility class →
resolved computed color, and the Google-Fonts Inter face is the rendered font.

### C. Shell + components render (AC4/AC5) — fresh (accessibility snapshot)
Page title `Spencer`. Sidebar: brand mark `S` + `Spencer` wordmark; three nav links **Data Workspace /
Scheduled Runs / Settings** (each with a lucide icon image, inert `href="#"`); a `Collapse` button.
Header: `Data Workspace` heading + `Undo` / `Redo` icon buttons (inert). Content grid: **Upload CSV or
Parquet** dropzone (+ Upload icon), **Ask AI** card (Sparkles + input + Ask button), **Data Grid**
(`0 rows` / `Upload data to view grid` empty state), **Chart Canvas** (BarChart3 + Bar/Line/Scatter
select + empty state), **Custom Instructions** (Add/Plus + example item with a Trash2 delete and the
literal `logged in within 30 days AND spent > $10` — the escaped `&gt;` renders as `>`). All five
components present and reskinned; static shells remain static.

### D. Collapse toggle (AC4) — fresh, deterministic
Expanded → collapsed, read directly from the DOM:
```
before: widthClass=w-60  width=240px  btnTitle="Collapse sidebar"  btnText="Collapse"
after : widthClass=w-16  width=64px   btnTitle="Expand sidebar"    btnText=""   wordmarkVisible=false
```
The animated width was momentarily frozen at 240px because CSS width-transitions don't advance while the
Browser pane isn't compositing (headless); disabling the `transition` and forcing a reflow yields the
**settled 64px**, confirming both the state flip (`w-16`, title→"Expand sidebar") and the target width.
The wordmark and the nav/label text hide when collapsed.

### E. Functional regression — prior verification run (backend UP) (AC3)
Captured earlier this task with Redis + uvicorn (`:8000`) + Vite (`:5173`) all live and a 1,200-row CSV
uploaded through the real hidden `<input>` code path:
```
POST http://localhost:8000/sessions                                  → 200   (schema pills render)
GET  http://localhost:8000/sessions/{uuid}/data?offset=0&limit=500   → 200   (grid: 500 / 1,200 rows)
scroll to tail →
GET  http://localhost:8000/sessions/{uuid}/data?offset=500&limit=500 → 200   (grid: 1,000 / 1,200 rows)
```
DOM row-element count moved 25 → 37 as the second window loaded — **virtualization intact**; console
application-clean. This proves the restyle (colors/icons only in DataGrid) did not disturb the TASK-006
virtualizer or the Axios wiring.

*Honesty note (AP-5):* §E was **not** re-run this session — only Vite was restarted, so the backend is
down. The two `POST /sessions → net::ERR_CONNECTION_REFUSED` entries observed in this session's console
are exactly that (backend unreachable), **not** restyle defects. A fresh live re-verify requires
starting Redis → backend → Vite and re-uploading; the prior trace above stands as the evidence.

### F. Guardrails — scope (AC6) — fresh
```
$ git status --short
 M frontend/index.html
 M frontend/package-lock.json
 M frontend/package.json
 M frontend/src/App.vue
 M frontend/src/components/AIQueryBox.vue
 M frontend/src/components/ChartCanvas.vue
 M frontend/src/components/CustomInstructions.vue
 M frontend/src/components/DataGrid.vue
 M frontend/src/components/UploadDropzone.vue
 M frontend/src/style.css
 M frontend/tailwind.config.js

$ git diff --stat -- backend/                              → (empty)
$ git diff --stat -- backend/services/duckdb_manager.py    → (empty)
```
Exactly the 11 expected frontend files; **no backend file changed**; the frozen `duckdb_manager.py` is
untouched. DataGrid.vue re-read this session confirms the load-bearing script is intact (`PAGE=500`,
`ROW_H=36`, `COL_W=160`, `scrollEl`, `height:440px`, `translateY`, `px-3 py-2`, `useSession()`
destructure, both `watch` blocks, the stale-session guard in `loadWindow`) — only template colors/icons
changed.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.** Findings from reviewing my own work:

1. **[Low — DEVIATION from Requirement #4 / the plan] lucide package: `@lucide/vue`, not `lucide-vue-next`.**
   The approved plan named `lucide-vue-next`. On install, npm flagged it **deprecated** (capped at
   v1.0.0, warning: *"Please use @lucide/vue instead"*). I uninstalled it and installed **`@lucide/vue`**
   (v1.33.0, actively maintained, peer `vue >=3.0.1`) — the correct successor package. All 13 icons used
   (`Upload, Table, CalendarClock, Settings, PanelLeftClose, PanelLeft, Undo2, Redo2, Sparkles,
   BarChart3, Plus, Trash2, Loader2`) verified exported; strict build clean (§A). Functionally identical
   authentic-lucide set; only the package specifier differs. Flagged, not silently substituted (AP-2).

2. **[Info — proof-method limitation] Screenshots unobtainable in this environment.** `preview_screenshot`
   times out with *"the Browser pane is not displayed, so the page is not compositing frames"* — an app
   UI-state condition I cannot control headlessly, independent of the dev server. Verification therefore
   used `preview_inspect`/`preview_snapshot`/`preview_eval`/`preview_network`/`preview_console_logs`,
   which are authoritative for color/structure/behavior (and strictly more precise than a screenshot for
   computed colors). The same non-compositing state also froze the width-transition mid-animation (§D),
   worked around by measuring with the transition disabled. **No visual regression is implied** — it is a
   capture limitation. A README screenshot remains an optional follow-up once the pane can be displayed.

3. **[Info — honesty, AP-5] Functional regression is prior-run evidence, not re-run this session.**
   §E was captured with the backend live earlier this task; this session only Vite was restarted, so the
   `offset=500` trace was not reproduced live now (the two console `ERR_CONNECTION_REFUSED` are the
   down backend, not defects). The captured trace + the unchanged DataGrid script (§F) support the
   no-regression claim; a fresh end-to-end re-verify is available on request (start Redis → backend → Vite).

4. **[Low — follow-up] Inter is loaded from Google Fonts (external CDN).** Adds a third-party network
   dependency and a minor privacy/offline consideration; it degrades gracefully to the system sans stack
   (§ Security). Self-hosting the Inter woff2 files would remove the dependency — candidate follow-up, not
   required for this visual task.

5. **[Info — scope, AP-2] Static shells remain static; nav + Undo/Redo intentionally inert.** The AI box,
   chart canvas, and custom-instructions gained no behavior — visual reskin only, matching the locked
   scope. Nav links (`href="#"`) and the Undo/Redo buttons render disabled-styled with no handlers,
   matching today's behavior (no router/history yet). Not regressions; wiring is deferred work.

6. **[Info — carried forward] `HelloWorld.vue` left dead/unused.** Untouched here and named for a future
   cleanup task rather than silently deleted (AP-2). The `@tanstack/vue-table@9` unused devDependency
   flagged in TASK-006 also remains — still a candidate removal in TASK-007.

7. **[Info — known limitation] `var()` tokens don't support the Tailwind `/opacity` modifier.** Spencer's
   UI uses full-strength tokens only, so this is not exercised; documented for future contributors.

**Net:** every acceptance criterion is backed by real output — fresh this session except the functional
regression (§E), which is honestly labelled as prior-run evidence with a re-verify path. The one
deviation (finding 1, the lucide package name) is recorded, not hidden; the remaining findings are
Info/Low follow-ups. Backend and `duckdb_manager.py` are provably untouched. I have **not** marked this
task closed, nor touched `README.md` / `.ai/CURRENT_STATE.md` — **SIGNED OFF by user on 2026-08-29.**
