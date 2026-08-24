# Spencer — Feature Backlog & Build Plan

Canonical list of the 34 target features with build status verified against the code
on **2026-08-22**. This is the single source of truth for "what's left." Statuses are
re-checked, not assumed. Sign-off remains the user's (workflow role); nothing here is
self-closed.

**Legend:** ✅ Built · 🟡 Partial · ⬜ Not built · ⏳ awaiting user sign-off

**Tally:** 7 built (all ⏳) · 10 partial · 17 not built → ~27 features with remaining work.

---

## Section A — Table (data prep)

| # | Feature | Status | Reality on disk / what's missing |
|---|---|---|---|
| 1 | Column profiler — null%, distinct, min/max/mean, top values, histogram | ✅⏳ | TASK-015; `profile_service.profile_column` + `ColumnProfilePanel.vue`, opened from grid ⋮ |
| 2 | Data-quality panel — auto flags | ✅⏳ | TASK-016; `quality_service.assess_table` (high-null/mixed/date-as-text/constant/dupes) + one-click Fix |
| 3 | Split / merge / extract columns (delimiter or regex capture) | ⬜ | No op; only free-form `calculated_column` SQL. Needs 1 transform op (SPLIT_PART/REGEXP_EXTRACT/CONCAT already allowlisted) |
| 4 | Date toolkit — parse→date, reformat, extract Y/M/D/weekday | 🟡 | parse text→date built (coercing cast, TASK-017). Missing reformat (STRFTIME) + extract-parts as new cols |
| 5 | Text toolkit — trim, case, strip-special, pad, regex find-&-replace | 🟡 | `string_normalize` = trim/case/**literal** replace/null-token. Missing regex-replace, strip-special, LPAD/RPAD |
| 6 | Binning — numeric → ranges/quantiles as category | ⬜ | No op; only hand-rolled CASE. Needs 1 transform op |
| 7 | Fill down/forward, outlier flagging | ⬜ | `impute_null` is whole-column aggregate only. Needs ordered window (LAG over rowid) + stats-based flag |
| 8 | In-grid power — multi-sort, drag-reorder, pin/freeze, hide, search, heatmap, inline edit | 🟡 | Only hide/show columns (1 of 7). Rest frontend-only |
| 9 | Transform recipe — replayable/exportable step list; re-apply to fresh upload | 🟡 | Server snapshot undo/redo exists; history stores only {op,column,ts}, not full params. No export, no re-apply |
| 10 | Export cleaned data — CSV / Excel / Parquet / JSON | 🟡 | CSV only (`csvExport.ts`). Missing Excel/Parquet/JSON |

## Section B — Canvas (dashboard)

| # | Feature | Status | Reality on disk / what's missing |
|---|---|---|---|
| 11 | More chart types (line/area/scatter/pie/stacked/heatmap/treemap/gauge/funnel/box) | 🟡 | Only bar/line/area/hbar/pie rendered (3 ECharts series). Scatter/stacked/heatmap/box need 2-D aggregate contract |
| 12 | Slicers / cross-filter every tile | ✅⏳ | Cross-filter substrate live (`ChartCanvas` + `AggregateFilter`). One equality slice; no standalone slicer widgets |
| 13 | Global date-range picker + drill-down | 🟡 | Drill-down built (= cross-filter). Date-range picker not built; wire is equality-only |
| 14 | KPI deltas — sparkline, ▲% vs prior, target thresholds | ⬜ | `KpiCard` renders a bare scalar; `KpiConfig` has no target/comparison fields |
| 15 | Drag/resize tile grid; save/load named dashboards | ⬜ | Fixed CSS grid; "saved dashboards deliberately out of scope for v1"; no persistence |
| 16 | Dashboard templates auto-built from schema | 🟡 | `ChartCanvas.seed()` = one generic heuristic. No named templates/picker |
| 17 | Export dashboard PNG/PDF; present/fullscreen | 🟡 | Per-tile PNG only. No dashboard export, no PDF, no fullscreen |
| 18 | "Explain this chart" (LLM narrates) | ⬜ | No endpoint/affordance |

## Section C — Query Engine (AI SQL)

| # | Feature | Status | Reality on disk / what's missing |
|---|---|---|---|
| 19 | Query history (re-run) + saved/named + favorites | ✅⏳ | TASK-012; `useQueryHistory` (localStorage) + `QueryHistory.vue`. "Favorites" == saved (no separate star) |
| 20 | Schema-aware autocomplete + clickable pills | ✅⏳ | `useCodeMirror.sqlExtension` + insert chips. Single-table; chips insert text (not live embedded pills) |
| 21 | Conversational refinement ("now group by month") | ⬜ | No turn memory; prev_sql only used inside the self-correction loop |
| 22 | Explain / optimize / fix SQL (turn DuckDB error → fix) | ⬜ | Raw error shown; internal `_classify_db_error` exists but not user-facing |
| 23 | Result → Canvas tile / Result → new working table | ⬜ | Results read-only; `/execute` is rolled-back sandbox (no materialize path) |
| 24 | Export results — CSV/Excel/clipboard; multiple tabs | 🟡 | CSV only. Missing Excel/clipboard/multi-tab |
| 25 | Parameterized queries (variables at run time) | ⬜ | SQL sent verbatim; no `:param`/`{{var}}` handling |

## Section D — Smart / AI (cross-cutting)

| # | Feature | Status | Reality on disk / what's missing |
|---|---|---|---|
| 26 | Auto-EDA on upload — 5 questions, one-click run | ⬜ | Not built; AI surface is only /ask, /execute, /instructions |
| 27 | Auto starter-dashboard from schema | ✅⏳ | `ChartCanvas.seed()` — deterministic (not LLM), ephemeral (lost on reload) |
| 28 | Auto-cleaning suggestions (date-as-text → cast, one-click) | ✅⏳ | TASK-016/017 — deterministic, genuinely one-click; rule-based not LLM |
| 29 | Data storytelling (LLM narrative of a dashboard/dataset) | ⬜ | Not built |
| 30 | Chart-type recommendation for a chosen field | ⬜ | Only implicit seed heuristic (temporal→line else bar) |

## Section E — Data in/out

| # | Feature | Status | Reality on disk / what's missing |
|---|---|---|---|
| 31 | More upload formats — xlsx/JSON/Parquet/TSV/paste | ⬜ | **CSV only** (`read_csv_auto`); allowlist default `csv`. UI advertises `.parquet` but backend rejects → real bug |
| 32 | Multi-table switcher UI | ⬜ | Backend fully supports multi-table; **no frontend switcher**. Cheapest win |
| 33 | Session export/import | ⬜ | No serialize/restore; DELETE is a stub |
| 34 | Shareable read-only dashboard snapshot | ⬜ | Not built; needs persistence + revisiting single-user model |

---

## Reusable foundations (why the plan is fast)

The remaining ~27 cluster onto **6 shared substrates** — build each once, dependents ride free:

1. **Transform-op plumbing** — schema union → 1 `_compile_structured` branch → 1 `OpDialog` block → 1 toolbar button. Allowlist already has SPLIT_PART/REGEXP_EXTRACT/REGEXP_REPLACE/LPAD/RPAD/CASE/DATE_PART/STRFTIME. Preview/apply/undo/redo/history are op-agnostic. → unlocks **3, 4, 5, 6** (7 is a harder window-based follow-on).
2. **LiteLLM AI-route pattern** — 1 route in `routers/ai.py` + 1 `AIService` method reusing `_resolve_model`/`_call_llm`/`_schema_context`. → unlocks **18, 22, 26, 29, 30**, and **21** (adds turn memory).
3. **Ingestion reader** — one branch in `analyze_and_register_table` on `config.ext_of(...)` + widen `SPENCER_UPLOAD_ALLOWED_EXT`. → **31** (+ fixes Parquet bug). Everything downstream is format-agnostic.
4. **Export encoders** — shared Excel/Parquet/JSON writer. → **10 + 24** together.
5. **Aggregate 2-D contract** — extend `AggregateRequest/Response` beyond 1-D `keys[]/values[]`. → the hard **11** types + richer slicers.
6. **Dashboard/session persistence store** — → **15 → 16, 13, 14, 17**, and **33, 34**.

---

## Fastest-path plan — 7 waves

Ordered by value-per-effort, Table-first per product priority. Each wave shares one foundation.
Cadence: batched per wave (build cluster → self-review with severity grades → **one user sign-off**),
reconciling "build it all fast" with the standing "check-in / sign-off" workflow role.

- **Wave 1 — Finish Table toolkit** (3 split/extract, 6 binning, 4 date-parts/reformat, 5 regex/pad/strip; then 7 fill-down/outlier). *Foundation 1. Highest features-per-effort; closes PARTIALs 4 & 5.*
- **Wave 2 — Round-trip data** (31 formats + Parquet-bug fix, 10 export cleaned, 24 export results). *Foundations 3 + 4.*
- **Wave 3 — In-grid power** (8). *Frontend-only; daily-use value.*
- **Wave 4 — AI batch** (22, 30, 26, 29, 18, 21). *Foundation 2.*
- **Wave 5 — Canvas chart types** (11). *Foundation 5.*
- **Wave 6 — Dashboard persistence + polish** (15 → 16, 13, 14, 17; slicer widgets for 12). *Foundation 6.*
- **Wave 7 — Cross-pillar connectors** (32 table-switcher [cheapest, backend done], 23 result→tile/table, 25 params, 34 snapshot, 33 session I/O). *Reuses Foundation 6.*

Waves are reorderable on request; #32 (multi-table switcher) is the single cheapest item and can be pulled forward any time.

---

## Pending sign-offs (built, in `tasks/active/`)

TASK-008, 009, 010, 012, 013, 015, 016, 017 — implemented + self-reviewed, awaiting user sign-off.
Building further on top of these compounds review debt; clearing them is the user's call.

## Constraints that shape the plan

- **ADR-006 single-table** — #32 is a *switcher* only; cross-table joins are excluded. Charts stay single-table.
- **Sign-off is the user's** — no self-close; `README.md` / `.ai/CURRENT_STATE.md` are the user's to edit.
- **No AI attribution** in commits/code/docs.
