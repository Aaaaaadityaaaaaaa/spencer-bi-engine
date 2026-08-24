# TASK-011

## Title
Canvas v1 — Power BI-style dashboard (Phase 5): a server-side `/aggregate` endpoint (Ibis→DuckDB SQL) plus
an auto-seeded, editable KPI-card row and one fully configurable chart tile (dimension / measure /
aggregation / bar·line·pie), refreshing over the FULL table on every data change.

## Objective
Make the **Canvas** section real. Today `CanvasView.vue` gates on a session and renders
`ChartCanvas.vue`, which is a **static mockup** (a decorative `<select>` + the literal text "Configure
axes to render chart"). This task delivers the flagship of the product vision — "a Power BI dashboard with
all KPI cards and all that features" — as a walking skeleton: on upload a dashboard appears instantly
(KPI cards + one chart), every tile is reconfigurable, the numbers are computed **server-side over the
whole table** (never a client-side reduction of a ≤1000-row page), and cleaning the data in the Table tab
auto-refreshes the whole dashboard via one `dataVersion` watch.

## Context
Locked with the user over one AskUserQuestion round (three "recommended" picks): (1) **aggregation = a
backend endpoint** — correct over the full table; additive code that never touches the frozen
`duckdb_manager.py`; the alternative (client-side over the ≤1000-row `/data` window) was rejected as
silently wrong past 1000 rows. (2) **scope = walking skeleton** — a KPI card row + exactly **one** fully
configurable chart tile, auto-refreshing on data change; deepen later. (3) **first load = auto-seeded +
editable** — Canvas infers sensible tiles from the schema on upload, then the user edits/adds.

The blocker exploration surfaced that there is **no working aggregation endpoint**: `POST /chart` and
`/execute` are stubs that `return b""`; only `GET /data` (raw rows, ≤1000/window) and `GET /schema`
return real data. The sanctioned design (the repo's own "Phase 5 — Not Started: Visual canvas /
charting") is a small server-side aggregate built with **Ibis → compiled DuckDB SQL → `run_readwrite`**,
mirroring the Phase 3 transform service (ADR-007/014/015).

Baseline = the still-unsigned TASK-010 working tree (itself on commit `a3c7162`). TASK-010 (Table
data-prep workspace) has **not** been committed or signed off, so this Canvas work sits on top of it; the
scope section (§F) separates TASK-011's own files from the inherited TASK-010 changes.

**Divergence note (AP-2):** `.ai/API.md` sketches a `POST /chart` (MessagePack, large-result) route; this
task adds a new, honestly-named `POST /aggregate` (JSON) instead and leaves the `/chart` stub untouched.
Reasons: `ChartRequest` *requires* `x_axis`/`y_axis` (no KPI/scalar case) and couples `chart_type` (a
pure frontend concern); and `/chart` is documented as the MessagePack large-result path, whereas an
aggregated top-N series is tiny, so **JSON** is right and matches the "small results stay debuggable"
choice already made for `/data`.

**Further divergences from the plan's file list (recorded, not hidden):**
- Added `frontend/src/utils/aggregations.ts` (agg labels + `allowedAggregations`/`coerceAggregation`)
  beyond the plan's listed utils (`columnKind.ts`, `chartPalette.ts`) — it keeps the "which aggregations
  are legal for this measure" rule in one place, shared by `KpiCard` and `ChartTile`.
- `KpiCard.vue` **owns its inline editor** (measure/aggregation pickers) rather than emitting an `edit`
  event to a parent-owned editor as the plan sketched. Same for the chart's pickers living in
  `ChartTile.vue`. Tiles stay presentational for *data* (they never fetch) but own their *config UI*.
- Auto-seed produces the planned **4** KPI cards; the user-add cap is `MAX_KPIS = 6` (the plan capped the
  seed at 4 but did not state an add cap).

## Requirements
1. **Backend endpoint** — `POST /sessions/{session_uuid}/aggregate` (JSON), serving **both** KPI cards
   (no dimension → scalar) and charts (dimension × measure → series). `AggregateRequest`
   (`dimension?`/`measure?`/`aggregation` Literal/`limit`) and `AggregateResponse`
   (`dimension`/`measure`/`aggregation`/`keys`/`values`/`compiled_sql`/`truncated`) added to
   `models/schemas.py`.
2. **Aggregate service** (`services/aggregate_service.py`, new) — mirrors `transform_service`: reuse its
   `_ibis_dtype`/`_unbound`/`_columns_of` (fresh PRAGMA per request, **never cached**); build an Ibis
   expression on the unbound table; **fail-closed validation** (unknown column, non-numeric measure for
   sum/avg, non-numeric/non-temporal for min/max, measure required unless `count`) → `AggregateError` →
   400; scalar `t.aggregate(value=…)` or grouped `t.group_by(dim).aggregate(value=…)`; ordering =
   temporal dim → key ASC, else value DESC; `.limit(clamped [1,200])`; compile via
   `ibis.to_sql(dialect="duckdb")`; run through `db_manager.run_readwrite`; coerce Decimal→float,
   date/datetime→ISO string.
3. **Route wiring** (`routers/query.py`) — `@router.post("/{session_uuid}/aggregate")` next to `get_data`;
   resolve the table with the existing `_resolve_table` (404 if unknown, single-table); map
   `AggregateError` → HTTP 400. `/chart` stub unchanged.
4. **Data layer** (`types.ts`, `api.ts`) — `Aggregation`/`ChartType`/`AggregateRequest`/`AggregateResponse`
   /`KpiConfig`/`ChartConfig`/`TileState<T>` types (snake_case to match FastAPI); `fetchAggregate(uuid,
   req, tableName?)` reusing the shared `http` client, `apiErrorMessage`, and `tableParam`.
5. **Column classification** (`utils/columnKind.ts`, new) — `columnKind(type)` →
   `'numeric'|'temporal'|'categorical'` over raw DuckDB type strings, plus
   `numericColumns`/`temporalColumns`/`categoricalColumns`/`dimensionColumns`.
6. **ECharts lifecycle** (`composables/useEchart.ts`, new) — `useEchart(elRef, optionRef)`: **modular**
   imports (`echarts/core` + Bar/Line/Pie + Grid/Tooltip/Legend/Dataset + CanvasRenderer), `echarts.use`
   once at module scope; init on mount, `setOption(opt, true)` on change (null → `clear()`),
   `ResizeObserver` → `resize()`, `onActivated` resize (keep-alive), `dispose()` + disconnect on unmount.
7. **Presentational tiles** — `KpiCard.vue` (new: formatted value, missing-column state, inline editor)
   and `ChartTile.vue` (new: field pickers + the ECharts option built from the `AggregateResponse` prop,
   always-mounted canvas host with overlaid loading/error/empty states, footer top-N notice + compiled
   SQL). `utils/chartPalette.ts` (new: 8-hue oklch palette). `utils/aggregations.ts` (new: agg labels +
   legality rules).
8. **Dashboard container** (`ChartCanvas.vue`, **rewrite**) — the **only** place that fetches aggregates:
   holds ephemeral KPI-list + chart config; `watch(sessionUuid, immediate)` → auto-seed + fetch all;
   `watch(dataVersion)` → refetch every tile with its **existing** config; per-tile monotonic staleness
   guard + uuid guard; a chart-**type** switch does **not** refetch (pure render concern); "Add KPI"
   (cap 6) + per-tile edit/remove.
9. **`package.json`** — move `echarts` from `devDependencies` → `dependencies` (runtime dep).
10. **Strict build** — `vue-tsc -b && vite build` clean.

## Files Expected To Change
- **Backend new:** `backend/services/aggregate_service.py`.
- **Backend edit:** `backend/models/schemas.py` (`AggregateRequest`/`AggregateResponse`),
  `backend/routers/query.py` (`/aggregate` route).
- **Frontend new:** `frontend/src/components/KpiCard.vue`, `frontend/src/components/ChartTile.vue`,
  `frontend/src/composables/useEchart.ts`, `frontend/src/utils/columnKind.ts`,
  `frontend/src/utils/aggregations.ts`, `frontend/src/utils/chartPalette.ts`.
- **Frontend edit/rewrite:** `frontend/src/components/ChartCanvas.vue` (rewrite),
  `frontend/src/services/api.ts` (`fetchAggregate`), `frontend/src/types.ts` (aggregate contract),
  `frontend/package.json` (echarts → dependencies).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; only its `run_readwrite` is called.
  Verified: `git diff -- backend/services/duckdb_manager.py` empty (§F).
- **The `POST /chart` MessagePack stub** in `routers/query.py` — left as-is for a future large-result
  path; the new `/aggregate` route is added above it, the stub body is unchanged (§F diff).
- **DataGrid's TASK-006 virtualizer** — not on this task's path.
- **ADR-006 single-table** — every aggregate targets the `_resolve_table`'d primary/`table_name`; no join
  path introduced. **ADR-012** — the frontend sends typed params as JSON; SQL is Ibis-built from
  live-schema-validated column names, never client-assembled.
- **`README.md` / `.ai/CURRENT_STATE.md`** — not touched; sign-off (and any roadmap update) is the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client-assembled SQL (ADR-012).** `fetchAggregate` (`services/api.ts`) sends the op as a typed JSON
  body (`{dimension, measure, aggregation, limit}`); it never string-builds a query. In
  `aggregate_service.aggregate`, the SQL is produced by **Ibis** (`ibis.to_sql(expr, dialect="duckdb")`)
  from column names first checked against the **live** schema in `_validate` — so a client value can only
  ever be a column *identifier that already exists*, never interpolated SQL text. There is therefore no
  user-SQL trust boundary on this route, and `sql_validator.py` (which gates *AI-generated* SQL) is
  correctly **not** on this path.
- **Fresh schema, never cached.** `aggregate()` calls `_columns_of(table_name)` (a `PRAGMA table_info`)
  on **every** request before building the expression, so a column dropped/renamed/retyped by a Table-tab
  transform is reflected immediately — a stale cached schema can't smuggle a now-invalid column into a
  compiled query.
- **Fail-closed validation → 400, never 500.** `_validate` rejects unknown columns, a missing measure for
  non-`count` aggs, a non-numeric measure for `sum`/`avg`, and a non-numeric/non-temporal measure for
  `min`/`max`; the route maps `AggregateError` → HTTP 400. A bad request is a client error surfaced
  per-tile, not a server fault.
- **Single-table only (ADR-006).** The route resolves the target via the existing `_resolve_table`
  (`routers/session.py`) → 404 if unknown; no client-forged table identity beyond what `POST /sessions`
  returned, and no join path exists.
- **Bounded result size.** `limit` is clamped to `[1, 200]` (`MAX_CATEGORIES`) server-side, so one request
  cannot group an unbounded key space; `truncated` flags a capped series to the UI.
- **No secrets, no new external calls.** All traffic is the existing same-origin `:8000` API via the
  single Axios client. No API keys touched; the AI NL→SQL path is not part of this task.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean (string-literal unions, `import type`, no unused, relative
   imports).
2. Upload → Canvas auto-seeds a KPI row + a default chart whose numbers equal the hand-computed
   COUNT/SUM/AVG over the full table; `/aggregate` responses carry correct `keys`/`values` + `compiled_sql`.
3. Reconfigure the chart (dimension/measure/aggregation/type) → series updates with correct values;
   bar/line/pie all render; a chart-**type** switch causes **zero** refetches.
4. Auto-refresh: a Table-tab transform (filter/drop) bumps `dataVersion` → every tile refetches with its
   config preserved and shows the new numbers; Undo reverts them.
5. Edge cases: non-numeric measure for SUM → friendly 400 in the tile (no crash); high-cardinality
   dimension → capped at top-N with `truncated=true` and a UI notice; a transform that drops a charted
   column → tile + affected KPI cards show a "reconfigure" state, and Undo self-heals.
6. Console application-clean; `git diff -- backend/services/duckdb_manager.py` empty; the `/chart` stub
   unchanged.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live; the frozen
`duckdb_manager.py` and the `/chart` stub unchanged; self-review with severity grades attached.
**Sign-off is the user's — I do not self-close this task, nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Status
COMPLETE — **signed off by the user on 2026-08-22**; moved to `tasks/completed/`.

Proof: fresh in-session evidence with the full stack live (Redis up, backend `:8000`, Vite `:5173`) —
strict build clean (§A); backend verified by 18 curl cases against a hand-computable 8-row CSV (§B);
live auto-seed with hand-checked numbers (§C); reconfigure + type-switch-without-refetch (§D);
auto-refresh + undo, dropped-column recovery, and top-N cap on a 60-category set (§E); scope + the one
console defect found and fixed (§F).

## Proof
Captured this session via `preview_*` MCP tools against the live stack, plus `curl` for the backend.
Screenshots are unobtainable headless (the Browser pane does not composite frames — same limitation as
TASK-008/009/010); verification reads real DOM / component `setupState` / network / canvas pixel data
after real interactions, and cross-checks all aggregate math by hand. Uploads were driven through the
**real** hidden `<input type=file>` (DataTransfer injection → real `POST /sessions`), so every UI step is
a true backend round-trip.

Test CSV — 8 rows, hand-computable (`West/Gadget` has a NULL `amount` on purpose):
```
region,product,amount,qty,sale_date
North,Widget,100,1,2024-01-05
North,Gadget,200,2,2024-01-12
South,Widget,300,3,2024-02-05
South,Gadget,500,4,2024-02-12
East,Widget,400,5,2024-03-05
East,Gadget,600,6,2024-03-12
West,Widget,700,7,2024-04-05
West,Gadget,,8,2024-04-12
```

### A. Build — strict `vue-tsc` (AC1)
`npm run build` (= `vue-tsc -b && vite build`):
```
vite v8.2.1 building client environment for production...
✓ 2488 modules transformed.
dist/index.html                   0.74 kB │ gzip:   0.39 kB
dist/assets/index-Bio7SjDi.css   15.11 kB │ gzip:   4.11 kB
dist/assets/index-DCRwSpcz.js   774.04 kB │ gzip: 265.59 kB
✓ built in 2.14s
```
`vue-tsc -b` passed — under strict flags this proves the `Aggregation`/`ChartType` string-literal unions,
the `TileState<T>` generic, and every wrapper resolve, and no import is left unused. (Vite warns the
chunk >500 kB — that's ECharts; a lazy-loaded Canvas route would fix it. Out of scope; noted in
self-review finding 3.)

### B. Backend — 18 curl cases against the 8-row CSV (AC2, AC5)
**Five scalar KPIs** (verbatim JSON):
```
{"aggregation":"count"}                        -> values:[8]                      COUNT(*)
{"aggregation":"sum","measure":"amount"}       -> values:[2800]                   SUM(amount)
{"aggregation":"avg","measure":"amount"}       -> values:[400.0]                  AVG(amount)
{"aggregation":"min","measure":"sale_date"}    -> values:["2024-01-05"]           MIN(date)->ISO string
{"aggregation":"count_distinct","measure":"region"} -> values:[4]                 COUNT(DISTINCT region)
```
Hand check: 100+200+300+500+400+600+700 = 2800 (NULL excluded); 2800/7 = 400; 4 regions. ✓

**Five grouped series** (verbatim):
```
sum(amount) by region  -> keys ["East","South","West","North"] values [1000,800,700,300]  (value DESC)
sum(amount) by sale_date -> 8 keys ASC, values [100,200,300,500,400,600,700,null]  (temporal ⇒ key ASC;
                            West/Gadget NULL amount preserved as null, not 0)
count_distinct(amount) by region -> East/North/South=2, West=1  (West's only non-null amount is 700)
count by region limit=1  -> keys ["North"] values [2]  truncated:true      (top-N cap works)
count by region limit=9999 -> LIMIT clamped to 200, values [2,2,2,2] truncated:false  (MAX_CATEGORIES)
```
Every compiled SQL is present and shows the expected `GROUP BY 1` + `ORDER BY … {ASC|DESC}` + `LIMIT`.

**Seven error paths** (verbatim `detail`):
```
sum on region   -> 400 "'sum' needs a numeric column; 'region' is string"
avg on product  -> 400 "'avg' needs a numeric column; 'product' is string"
min on product  -> 400 "'min' needs a numeric or date/time column; 'product' is string"
sum, no measure -> 400 "aggregation 'sum' requires a measure column"
dimension 'nope'-> 400 "column 'nope' not found"
count measure 'nope' -> 400 "column 'nope' not found"
aggregation 'median' -> 422 (Pydantic Literal rejects it before our code runs)
unknown session -> 404 "No tables in this session"
```
Fail-closed validation and the 400/404 mapping both hold.

### C. Live auto-seed — hand-checked numbers (AC2)
Upload `canvas_test.csv` → navigate to Canvas → read `ChartCanvas` `setupState`:
```
cards:  TOTAL ROWS 8 | SUM OF AMOUNT 2,800 | AVERAGE OF AMOUNT 400 | SUM OF QTY 36
chart:  "Sum of amount by region"  keys ["East","South","West","North"]  values [1000,800,700,300]
```
Exactly one `/aggregate` request per tile (per-tile `kpiSeq` all = 1). SUM(qty) = 1+2+…+8 = 36. ✓
The pie/bar geometry was confirmed proportional to the data (earlier pixel sampling), and the **oklch
palette resolves in Canvas2D** — `oklch(0.587 0.174 252.167)` drew as `rgb(7,125,223)`, zero black
pixels, so no hex fallback is needed.

### D. Reconfigure + type-switch without refetch (AC3)
Reconfiguring dimension/measure/aggregation produced correct values (incl. the subtle
`count_distinct(amount) by region` → West = 1, nulls excluded). Switching chart **Type** twice
(bar→line→bar) while reading `performance.getEntriesByType('resource')`:
```
aggregateRequestsDuringTwoTypeSwitches: 0     seriesType flips bar/line   xLabelRotate 35  hideOverlap true
```
The `sameQuery` guard in `onChartUpdate` keeps a pure render change off the network.

### E. Auto-refresh, dropped-column recovery, top-N cap (AC4, AC5)
**Dropped-column recovery** — via the real cleaning dialog, dropped `amount`:
```
cards:  SUM OF AMOUNT / AVERAGE OF AMOUNT -> "Column no longer exists — pick another."
chart:  error "column 'amount' not found" + "A column used by this chart no longer exists — pick another above."
        (TOTAL ROWS 8 and SUM OF QTY 36 kept working -- tiles are independent)
```
**Undo** → every tile restored with no manual reconfiguration:
```
cards:  8 | 2,800 | 400 | 36        chart: keys ["East","South","West","North"] values [1000,800,700,300]
```
**Top-N cap** — uploaded a 60-distinct-category set (`City_01..City_60`):
```
cards:  TOTAL ROWS 60 | SUM OF AMOUNT 18,300 | AVERAGE OF AMOUNT 305 | SUM OF QTY 1,830
chart:  seriesLen 50   truncated true   notice "Showing the top 50 categories only."
        firstThree City_60=600, City_59=590, City_58=580  (value DESC, top-N kept)
```
Hand check: Σ 10·(1..60) = 18,300; 18,300/60 = 305; Σ(1..60) = 1,830. ✓ The re-seed on a new upload
(different schema) also fired correctly.

### F. Scope + the console defect found and fixed (AC6)
```
$ git diff -- backend/services/duckdb_manager.py     → (empty)          # frozen file untouched
$ git diff -- backend/routers/query.py               → adds /aggregate ABOVE the unchanged /chart stub
```
**Console defect found and fixed (real):** the first render logged
`[ECharts] Specified grid.containLabel but no use(LegacyGridContainLabel); use grid.outerBounds instead`
— ECharts 6 **silently ignores** `grid.containLabel` in a modular build, so rotated axis labels would be
clipped. Replaced it with the documented equivalent `outerBoundsMode:'same'` + `outerBoundsContain:
'axisLabel'` (needs no extra module). Re-verified live: `getOption()` shows `containLabel:false` +
`outerBoundsMode:'same'`; axis ink reaches within 7 device-px of the canvas bottom and 9 px of the left,
i.e. the grid shrinks to fit the labels. Strict build re-run clean after the fix.

**Scope note (honest):** the working tree also carries the still-unsigned **TASK-010** changes (App.vue,
DataGrid.vue, UploadDropzone.vue, useSession.ts, TableView.vue, CleaningToolbar.vue, OpDialog.vue,
TASK-010.md), because TASK-010 was never committed. TASK-011's own files are the ones in "Files Expected
To Change". Backend changes are **purely** TASK-011 (TASK-010 was frontend-only). The two shared frontend
files `types.ts` and `api.ts` show cumulative diffs (TASK-010's transform contract + TASK-011's aggregate
block) since neither task is committed; TASK-011's additions to them are the `Aggregation`/`ChartType`/
`Aggregate*`/`*Config`/`TileState` types and `fetchAggregate` respectively.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Info — proof method] Live proof via `preview_*`; screenshots unobtainable headless.** Same
   Browser-pane non-compositing limitation as TASK-008/009/010. Behavior verified by reading real DOM /
   component `setupState` / network / canvas pixel data after real interactions and real backend
   round-trips. Because `requestAnimationFrame` is paused in the non-compositing pane, a synchronous draw
   was forced for pixel sampling via `getInstanceByDom(el).setOption({animation:false}, false)` — a
   test-only mutation that the next real `setOption(opt, true)` replaces wholesale.
2. **[Low — verification gap] The 50-label crowded render is proven at the option level, not pixel-sampled.**
   During the 60-category pass the Browser pane collapsed to a 0×0 viewport, so `getImageData` had a
   zero-width source. The crowding mitigation is confirmed present in the live option (`rotate:35`,
   `hideOverlap:true`, `outerBoundsContain:'axisLabel'`), and pixel proof that labels fit exists for the
   4-category case (§F). Not re-sampled at 50 labels; flagged rather than hidden.
3. **[Info — bundle size] Main chunk is 774 kB (ECharts ~500 kB of it).** Vite warns >500 kB. The modular
   ECharts import already excludes maps/GL/unused charts; the clean next step is a lazy-loaded Canvas
   route (`defineAsyncComponent` / route-level `import()`). Out of scope for the skeleton; worth doing
   before shipping more tiles.
4. **[Low — error rendering] A 422 (Pydantic) `detail` is an array, which `apiErrorMessage` would render
   as `[object Object]`.** Unreachable from the UI — the aggregation `<select>` only offers allowlisted
   values, so the client can't send an out-of-Literal aggregation (§B shows the 422 is reachable only via
   raw curl). Every reachable error is a 400 with a string `detail`, which renders correctly. Flagged as
   a latent rough edge if a future field becomes free-text.
5. **[Info — console: CORS on `/transform/preview`] One CORS-blocked request appears in the console.** It
   is a `/transform/preview` call — **not** on the Canvas `/aggregate` path — fired by the preview pane's
   own automated interaction probing between my evals (the pane opens dialogs / clicks buttons on its
   own; diagnosed earlier via an `isTrusted` capture listener). The app's own `/aggregate` calls, including
   the three dropped-column 400s, went through CORS fine and rendered their friendly per-tile errors.
   Environment artifact, not an application defect.
6. **[Low — coverage] Pie was exercised earlier this session but not re-verified after the grid fix.**
   The `grid.*` change only affects the bar/line branch (pie returns a separate option object with no
   `grid`), so pie is unaffected by the fix; bar and line were both re-verified post-fix (§D/§F). Noted
   for completeness.
7. **[Info — persistence] Tile config is ephemeral.** It survives tab switches (App.vue `<keep-alive>`,
   verified zero refetches) but not a page reload — saved dashboards are deliberately out of scope for
   Canvas v1, as the plan states.
8. **[Info — carried forward] Builds on the unsigned TASK-010 working tree** (itself on `a3c7162`).
   TASK-008/009/010 sign-off all remain the user's; this task's own diff is the file set in §F. I have
   **not** self-closed any of them, nor touched `README.md` / `.ai/CURRENT_STATE.md`.

**Net:** the Canvas v1 loop — upload → instant auto-seeded dashboard → reconfigure any tile (correct
server-side math over the full table) → clean the data in Table → whole dashboard auto-refreshes → undo
reverts — is proven end-to-end against the live backend, with 18 hand-checked backend cases, correct
null/temporal/top-N handling, a real console defect found and fixed, and the frozen `duckdb_manager.py`
plus the `/chart` stub provably untouched. The honest gaps are verification-side (findings 2 and 6, both
a consequence of the headless pane) and one latent, currently-unreachable error-rendering edge (finding
4). I have **not** marked this task closed — **awaiting your sign-off.**
