# TASK-009

## Title
Power BI-style restructure — vue-router shell + Table / Canvas / Ask AI sections (structure-first)

## Objective
Turn Spencer's single stacked page (`App.vue`) into a Power BI-style multi-section app with **real
navigation**: three routed sections — **Table** (upload + schema pills + the virtualized grid),
**Canvas** (chart builder shell), and **Ask AI** (NL-query + custom-instructions shell) — behind a
sidebar nav rail, a dynamic per-route header title, and a preserved collapse toggle. This ships ONLY the
structure: the working grid moves into Table **intact**; Canvas and Ask are clean shells the later chart
and LiteLLM phases fill in. **No backend changes; builds on the TASK-008 design tokens.**

## Context
Direction locked over two AskUserQuestion rounds: (1) AI abstraction = **LiteLLM** (later phase);
(2) build order = **Structure first** (this task); (3) Canvas v1 = **one chart builder** (later phase).
The user asked, verbatim, for "canvas as a different section and the table like a different one and one
where we can query everything with the api ai integrated." Exploration confirmed: no `vue-router`
present; `main.ts` is a 5-line bootstrap; no path aliases (relative imports); strict TS
(`noUnusedLocals`/`noUnusedParameters`/`erasableSyntaxOnly`); `useSession` is a **module-scoped reactive
singleton** (session survives navigation with zero prop wiring); all five components are independent
(only `App.vue` imported them), so they relocate into views cleanly.

**Roadmap note (AP-2):** the documented "next recommended task" was TASK-007 (Data Grid v2). This
restructure is an explicit reorder to the user's current priority — flagged, not silent.
**Divergence note (AP-2):** `.ai/ARCHITECTURE.md` frames the AI entry as a Ctrl+K palette + Review Gate
modal; the user explicitly asked for a dedicated **section**, so AskView-as-a-page is a conscious choice
(a palette can layer on later as an *additional* entry point, not a replacement).

## Requirements
1. **Router** — new `frontend/src/router/index.ts`: `createWebHistory`; routes `/`→redirect `/table`,
   `/table`→TableView, `/canvas`→CanvasView, `/ask`→AskView; `meta.title` per route typed by **module
   augmentation** of `RouteMeta` (type-only — safe under `erasableSyntaxOnly`, no enums).
2. **Views** — new `frontend/src/views/`: `TableView` (`UploadDropzone` + `DataGrid`, schema pills ride
   inside the dropzone), `CanvasView` (`ChartCanvas` + no-data guard), `AskView` (`AIQueryBox` +
   `CustomInstructions` + no-data guard). No-data guard reads `sessionUuid` from `useSession()`.
3. **Shell** — `frontend/src/App.vue`: sidebar + header + `<router-view>`. Nav → `<RouterLink>`s
   (`custom` slot, `isActive` styling) for the three routes; old Scheduled Runs / Settings kept as inert
   "Coming soon" items. Header title dynamic via `useRoute().meta.title`. **Collapse toggle + brand mark
   preserved verbatim.** `<keep-alive>` wraps the view so grid scroll state survives nav.
4. **main.ts** — install the router (`createApp(App).use(router).mount('#app')`), keep `./style.css`.
5. **Strict build** — `npm run build` (`vue-tsc -b && vite build`) passes; every relocated icon/`ref`
   import used in the file it lands in.
6. **Preserve TASK-006 behavior** — DataGrid virtualizer guardrails untouched (`PAGE=500`, `ROW_H=36`,
   `COL_W=160`, `scrollEl`, `height:440px`, `translateY`, `useSession` destructure); the second `/data`
   window at `offset=500` still fires on scroll after relocation.

## Files Expected To Change (frontend only)
- **New:** `frontend/src/router/index.ts`; `frontend/src/views/TableView.vue`,
  `frontend/src/views/CanvasView.vue`, `frontend/src/views/AskView.vue`.
- **Edit:** `frontend/src/App.vue` (shell + RouterLink nav + `<router-view>` + dynamic title);
  `frontend/src/main.ts` (install router); `frontend/package.json` (+ `package-lock.json`) — add
  `vue-router`.

## Files That Must NOT Change
- **All of `backend/`** — frontend-only task; `backend/services/duckdb_manager.py` (frozen) untouched.
  Verified: `git diff -- backend/` empty (§F).
- `frontend/src/composables/useSession.ts`, `services/api.ts`, `types.ts` — pure logic; reused, not edited.
- The five components' **internal logic** — relocated by reference from `App.vue` into views; not edited
  in TASK-009. (Their `M` status in `git status` is TASK-008's still-unsigned restyle — §F, Self-Review 7.)
- `frontend/src/components/HelloWorld.vue` — dead/unused; left as-is (AP-2).

## Security Considerations (AP-8 — name the exact path each control covers)
Structural/navigation change only. **No new backend call, no new SQL, no new user-input path.**
- `vue-router` runs client-side; routes map to local view components — no data fetch on navigation. The
  only network call in the flow is the pre-existing `POST /sessions` + `GET …/data` from the upload path
  (unchanged from TASK-006), which still runs through `services/api.ts`.
- The AI-SQL path (`sql_validator` → `run_sandboxed` → human Review Gate) is **not wired here** — AskView
  hosts the same static shell as before; no SQL is constructed or executed by this task.
- `createWebHistory` deep links require SPA fallback to `index.html`; Vite dev + `vite preview` provide
  it. No new external dependency beyond `vue-router` (no CDN/runtime fetch). No secrets added to client.

## Acceptance Criteria
1. Strict `vue-tsc -b` build clean (route-meta types resolve; no stray imports).
2. Routing: `/`→`/table`; nav to `/table`/`/canvas`/`/ask` updates URL + dynamic header title; browser
   back button works.
3. No-data guard on Canvas/Ask before a session; their real shells render once a session exists.
4. Table upload → schema pills + grid first window (`offset=0`); scroll → **second `/data` at
   `offset=500`** appends (virtualizer intact after relocation); console application-clean.
5. Collapse toggle still flips `w-60 ↔ w-16` (wordmark hides, title flips).
6. Scope: only `frontend/**` + task file changed by this task; `git diff -- backend/` empty.

## Definition Of Done
All acceptance criteria shown as real output; frontend-only with the entire backend (and
`duckdb_manager.py`) unchanged; all TASK-006 behavior preserved; self-review with severity grades
attached. **Sign-off is the user's — I do not self-close this task.**

## Status
COMPLETE — **awaiting user sign-off** (not self-closed).

Proof: fresh in-session evidence with the full stack live (Redis `PONG`, backend `/health` ok, Vite
`:5173`) — strict build clean (§A); routing + dynamic title + back button (§B); no-data guard → real
shells after session (§C); upload → `offset=0` then scroll → `offset=500` (§D); collapse toggle (§E);
frontend-only scope with backend diff empty (§F).

## Proof
Captured this session via `preview_*` MCP tools against the live stack. Screenshots are unobtainable
headless (Browser pane not compositing — same limitation as TASK-008); verification uses
`preview_eval`/`preview_network`/`preview_console_logs`, authoritative for URL/structure/behavior.

### A. Build — strict `vue-tsc` (AC1)
`npm run build` (= `vue-tsc -b && vite build`):
```
> frontend@0.0.0 build
> vue-tsc -b && vite build
vite v8.2.1 building client environment for production...
✓ 1890 modules transformed.
dist/index.html                   0.74 kB │ gzip:  0.39 kB
dist/assets/index-ahUN2bk4.css   11.63 kB │ gzip:  3.42 kB
dist/assets/index-BiltvANJ.js   179.44 kB │ gzip: 64.88 kB
✓ built in 1.92s
```
`vue-tsc -b` runs first and passed — under strict flags this proves the `RouteMeta` augmentation types
resolve and no relocated icon/`ref` import is left unused (module count 1868→1890, JS 150→179 kB as
vue-router links in).

### B. Routing + dynamic title + back button (AC2)
Root redirect + nav rail (fresh page load at `/`):
```
path=/table  title="Table"  navLinks=[Table, Canvas, Ask AI]  comingSoon=[Scheduled Runs, Settings]
```
Navigating (native RouterLink click) then `history.back()`:
```
click Canvas  → path=/canvas  title="Canvas"   guard="Load a dataset in the Table tab to build a chart."
click Ask AI  → path=/ask     title="Ask AI"   guard="Load a dataset in the Table tab to ask questions…"
history.back()→ path=/canvas  title="Canvas"   (browser back works)
```

### C. No-data guard → real shells once a session exists (AC3)
Before upload (§B): Canvas/Ask show the "No data loaded" guard.
After upload (session live), re-navigating:
```
/canvas title="Canvas"  hasChartSelect=true  body="Chart Canvas  Bar Chart/Line Chart/Scatter  Configure axes to render chart"
/ask    title="Ask AI"  hasAskInput=true     hasCustomInstructions=true  body="Ask AI  Ask  SELECT region, SUM(profit)… Edit Execute"
```
The reactive `useSession` singleton + `<keep-alive>` swap the guard for the real shell across nav.

### D. Upload → grid first window, scroll → second window (AC4) — virtualizer intact after relocation
1,200-row CSV driven through the real hidden `<input type=file>` on TableView:
```
dropzone: "grid_probe.csv  1,200 rows · 3 columns — click to replace"
schema pills: id BIGINT · name VARCHAR · amount DOUBLE   (3 pills)
grid: "500 / 1,200 rows"   scrollHeight ≈ 18,033px (= 500 × 36px → ROW_H preserved)
```
Network trace (backend `:8000`):
```
POST /sessions                                                        → 200
GET  /sessions/8714b22f…/data?offset=0&limit=500&table_name=t_8714…   → 200   (first window)
— set scrollTop→scrollHeight, dispatch 'scroll' —
GET  /sessions/8714b22f…/data?offset=500&limit=500&table_name=t_8714… → 200   (second window)
```
`preview_console_logs`: only `[vite] connecting/connected` debug lines — application-clean. (The scroll
was driven by a manual `scroll`-event dispatch + network inspection because hidden tabs throttle timers
and pause rAF; the `offset=500` GET is authoritative that the relocated virtualizer fired.)

### E. Collapse toggle (AC5)
Click toggle, measure with transition disabled + reflow (Vue microtask flush between click and read):
```
expanded_before: cls=w-60  title="Collapse sidebar"  wordmark=visible
collapsed:       cls=w-16  width=64px  title="Expand sidebar"  wordmark=hidden
expanded_after:  cls=w-60  title="Collapse sidebar"  wordmark=visible
```

### F. Scope (AC6)
```
$ git status --short
 M frontend/index.html            ┐
 M frontend/package-lock.json     │
 M frontend/package.json          │
 M frontend/src/App.vue           │  ← TASK-009 edits: App.vue, main.ts, package.json(+lock)
 M frontend/src/components/AIQueryBox.vue        ┐
 M frontend/src/components/ChartCanvas.vue       │
 M frontend/src/components/CustomInstructions.vue│  ← TASK-008 (unsigned restyle), NOT this task
 M frontend/src/components/DataGrid.vue          │
 M frontend/src/components/UploadDropzone.vue    ┘
 M frontend/src/main.ts           │
 M frontend/src/style.css         ┘ (index.html/style.css/tailwind also TASK-008)
 M frontend/tailwind.config.js
?? frontend/src/router/           ← new (TASK-009)
?? frontend/src/views/            ← new (TASK-009)
?? tasks/active/                  ← this task file (+ TASK-008)

$ git diff --stat -- backend/     → (empty)
```
Backend provably untouched; `duckdb_manager.py` in the empty backend diff.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Info — proof method] Live proof via `preview_*`; screenshots unobtainable headless.** Same Browser-
   pane non-compositing limitation as TASK-008. Structure/URL/behavior verified via
   `preview_eval`/`preview_network`/`console_logs`, which are authoritative. The scroll-driven second
   window (§D) required a manual `scroll`-event dispatch because hidden tabs throttle `setTimeout` (~1 s)
   and pause `requestAnimationFrame`; the `offset=500` network GET is the real signal.
2. **[Low — design choice, AP-2] AskView gates *both* AIQueryBox and CustomInstructions behind a session.**
   Custom Instructions (the business dictionary, `bizdict_version`) could reasonably be editable before
   data loads. Gated for a clean v1 empty state per the plan; if pre-loading terms is wanted, split the
   guard so instructions render without a session. Flagged, not silently decided.
3. **[Low — divergence from repo docs, AP-2] AI built as a `/ask` section, not the documented Ctrl+K
   palette + Review Gate modal** (`.ai/ARCHITECTURE.md`). Done per explicit user request ("one section
   where we can query"). A command palette can be added later as an *additional* entry point.
4. **[Info — roadmap reorder, AP-2] Documented next task was TASK-007 (Data Grid v2).** This restructure
   was prioritized per the user's current direction; TASK-007 remains earmarked/unstarted.
5. **[Info — keep-alive scope] `<keep-alive>` caches all three views unbounded.** Fine for three light
   views; DataGrid scroll state now persists across nav (intended). If views grow heavy/stateful later,
   consider `:include`/`:max`.
6. **[Info — deploy] `createWebHistory` needs SPA fallback for deep links.** Vite dev + `vite preview`
   handle it; a production static host needs a catch-all rewrite to `index.html`. Noted for deploy.
7. **[Info — TASK-008 coupling] The working tree still carries TASK-008's unsigned restyle** (5 components
   + `index.html`/`style.css`/`tailwind.config.js`). TASK-009 builds on those tokens; both await sign-off.
   TASK-009's own files: `App.vue`, `main.ts`, `package.json`(+lock), `router/`, `views/`.
8. **[Info — initial title tick] `route.meta.title` is empty for one microtask at `START_LOCATION`**
   before the `/`→`/table` redirect resolves; observed to settle to "Table" with no visible flash. A
   fallback (`route.meta.title ?? 'Spencer'`) would remove the theoretical tick — optional.
9. **[Low — carried forward] `HelloWorld.vue` still dead; `@tanstack/vue-table@9` still an unused
   devDep.** Untouched by this task; cleanup candidates remain (as flagged since TASK-006/008).

**Net:** every acceptance criterion is backed by fresh in-session output with the full stack live. The
relocated DataGrid virtualizer fires the `offset=500` window (§D) — the load-bearing regression is
proven, not assumed. Backend and `duckdb_manager.py` are provably untouched. Two conscious deviations
(findings 2, 3) and the roadmap reorder (4) are flagged, not hidden. I have **not** marked this task
closed nor touched `README.md` / `.ai/CURRENT_STATE.md` — **SIGNED OFF by user on 2026-08-29.**
