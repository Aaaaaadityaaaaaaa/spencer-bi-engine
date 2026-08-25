# TASK-031 — Wave 6b: KPI sparklines (#14, part 2)

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
Backlog **#14 — "KPI deltas / targets"**, second and final slice. TASK-030 gave each `KpiCard` a
▲/▼ delta-vs-target chip; this adds the other half of a Power-BI KPI visual — a **trend sparkline**:
a tiny inline line of the same metric over time, so a card shows not just "where we are" (scalar) and
"vs goal" (delta) but "which way it's going" (trend).

**Goal:** each KPI card can plot a mini sparkline of its measure/aggregation grouped by a chosen
**temporal column**, in chronological order, reflecting the active cross-filter. A **"Trend by"** picker
in the card editor selects the date column (or turns it off). Cards auto-seed a trend when the dataset
has a temporal column, so sparklines appear the instant a file lands (matching `ChartCanvas.seed()`'s
"a dashboard exists immediately" philosophy).

**No backend change.** The trend is the existing `POST /aggregate` with `dimension=<temporal col>`,
which `aggregate_service` already returns ordered chronologically (temporal dimensions sort by key ASC).
`KpiConfig` is frontend-only view state, so the new `trendDimension` field is not a wire-contract change
and persists into a saved dashboard (#15) for free, exactly like `target`/`targetMode`.

**Explicitly out of scope (follow-ons):**
- **Date bucketing / granularity** (trend by *month/quarter* instead of raw date) → **#13 date-range**.
  Today the aggregate groups by the raw date value and clamps to `limit`; a sparkline sends `limit=200`
  so ordinary demo series come through whole and in order. For a temporal column with >200 distinct
  points the server returns the earliest 200 chronologically — acceptable for MVP demo data; true
  bucketing (Ibis `.truncate()` + a `bucket` param) belongs with the date-range work that also needs
  range predicates. Called out, not silent.
- **Delta vs *prior period*** (▲% vs last month) → also #13 (needs range predicates on the equality-only
  `AggregateFilter`).

## What changed
### Frontend (only)
- **`types.ts`** — `KpiConfig` gains `trendDimension?: string | null` (optional ⇒ existing cards and
  saved dashboards are unaffected; camelCase, never sent to the backend).
- **`components/KpiCard.vue`**
  - **Inline SVG sparkline** under the value/target line, rendered from a `trend` prop (an
    `AggregateResponse`). Hand-rolled `<polyline>` in a `0 0 100 24` viewBox with
    `preserveAspectRatio="none"` + `vector-effect="non-scaling-stroke"` so it stretches to the card
    width with a crisp 1.5px stroke — **no ECharts instance per card** (lighter + zero extra deps than
    the ChartTile path; a KPI spark needs no axes/tooltip). No end-dot: under non-uniform scaling a
    round marker would distort to an ellipse, so the line stands alone. A flat (constant) series is
    drawn as a centered horizontal line rather than pinned to the axis floor.
  - **Robust:** renders only when the series has **≥2 finite-number** points. A non-numeric series
    (MIN/MAX-over-date ⇒ ISO strings), a single point, an empty/errored/loading trend, or a card in its
    own scalar-error state ⇒ **no sparkline, no crash**. Cards with no `trendDimension` look identical
    to before TASK-031.
  - **Editor:** a **"Trend by"** `<select>` (None + each temporal column), shown only when the dataset
    has ≥1 temporal column. Changing it is display-adjacent — it changes only the trend query, never the
    scalar.
- **`components/ChartCanvas.vue`**
  - A parallel **per-card trend fetch**: `kpiTrend` state map + `kpiTrendSeq` monotonic guard +
    `loadKpiTrend(cfg)` (fires the existing `fetchAggregate` with `dimension=cfg.trendDimension`,
    `limit=200`, and the active `filtersFor()`; no-ops to a cleared state when `trendDimension` is null).
  - `seed()` and `addKpi()` set `trendDimension` to the first temporal column when one exists.
  - `loadAll()` also loads every card's trend, so the `dataVersion` (post-transform) and cross-filter
    refetch paths cover sparklines with no extra wiring; the `sessionUuid` watch clears `kpiTrend`.
  - `onKpiUpdate` guard extended: the **scalar** refetches only on a `measure`/`aggregation` change
    (unchanged from TASK-030); the **trend** refetches on a `measure`/`aggregation`/`trendDimension`
    change; `target`/`targetMode` edits still refetch **neither**.

### Backend
**None.** No schema, endpoint, service, or config change. The trend uses the existing aggregate contract.

## Config
**None new.** No env vars, no secrets, no new client-controlled server surface.

## Acceptance criteria
1. ✅ **Sparkline renders** for a KPI with a `trendDimension` and a numeric series (≥2 points), as a
   chronological inline line spanning the card.
2. ✅ **Same metric, grouped by time.** The sparkline uses the card's own `measure`/`aggregation`,
   grouped by the chosen temporal column, ordered oldest→newest (server orders temporal dims ASC).
3. ✅ **Editor "Trend by" round-trips.** Picker lists temporal columns + None; selecting one shows the
   sparkline and refetches **only** the trend; None removes it; the picker is hidden when the dataset
   has no temporal column.
4. ✅ **No sparkline on degenerate series.** Non-numeric (ISO-date) values, <2 points, an errored/empty
   trend, or a card in scalar-error state ⇒ no sparkline, no crash. Target-less/trend-less cards look
   unchanged.
5. ✅ **Cross-filter reflected.** A slice refetches the sparkline so it shows the sliced trend
   (consistent with the delta chip, which already uses the cross-filtered value).
6. ✅ **No wasted fetch.** Editing target/direction fires **no** request; changing `trendDimension`
   fires **only** the trend aggregate; changing measure/aggregation fires **both** scalar and trend.
7. ✅ **Strict build green.** `vue-tsc -b && vite build` clean.
8. ✅ **Must-not-change:** `README.md`, `.ai/CURRENT_STATE.md` untouched; footprint = `types.ts`,
   `KpiCard.vue`, `ChartCanvas.vue` (+ this spec).

## Verification (real output)
**Environment:** real Redis (portable `redis-server.exe`), backend `:8000` (`/health` → `{"status":"ok"}`),
Vite preview `:5173`, authenticated as `kpitest@example.com`. **Dataset:** `spark_demo.csv` uploaded live
(12 rows — `order_date` DATE card 6, `region` VARCHAR card 2, `revenue` BIGINT card 12; 2 regions × 6
months). Verified in-browser via DOM/`getComputedStyle`/`performance.getEntriesByType('resource')` counts
(this headless preview has a 0×0 viewport, so screenshots and ECharts-canvas pixel-clicks are unavailable —
DOM + network are the authoritative proof).

- **AC1/AC2 — renders, chronological, same metric by time.** On upload, all 3 seeded KPI cards auto-drew a
  sparkline (`order_date` auto-seeded as the trend). "Sum of revenue" `<polyline>` points decode to the
  monthly sums `[180, 240, 250, 310, 330, 360]` (scalar total **1,670** ✓), normalised into the `0 0 100 24`
  viewBox as a clean rising line; `title`="Sum of revenue by order_date: 6 points, 2024-01-01 → 2024-06-01"
  (oldest→newest, x ascending). "Total rows" is a constant series (2/month) → flat centered line.
- **AC3/AC6 — editor round-trip + fetch boundaries** (measured `/aggregate` call deltas): initial mount = 7
  calls (3 scalar + 3 trend + 1 chart). Set **Target=300** → **+0** calls, chip + "Target: 300" rendered.
  **Trend by → None** → **+0** calls, sparkline removed, scalar unchanged (1,670). **Trend by → order_date**
  → **+1** call (trend only), scalar untouched, identical sparkline restored. **Aggregation sum→avg** →
  **+2** calls (scalar+trend), value 139.17. "Trend by" picker lists exactly `[None, order_date]`.
- **AC4 — degenerate series.** Trend→None removed the sparkline (no crash). `measure=order_date, agg=max`
  (allowed aggs correctly limited to min/max/count/count_distinct for a DATE) → scalar shows ISO string
  **"2024-06-01"**, the trend aggregate is fetched but its values are ISO strings → filtered to `[]` → **no
  sparkline, `error: null`** (graceful). The `n < 2` guard covers the empty/single-point cases.
- **AC5 — cross-filter.** Fired the chart tile's real `select('North')` event (the same `@select` a bar
  click emits — used directly because the 0-width canvas has no clickable pixels). Chip: **"Filtered by
  region = North"**. Total rows 12→**6** (still flat); Avg revenue 139.17→**161.67** (=970/6 ✓); the
  sparkline reshaped to the North-only series `2,22 21.2,13.67 40.4,17.00 59.6,5.33 78.8,10.33 98,2` — every
  point matches the hand-computed normalisation, showing the Feb→Mar **dip** (North Mar 130 < Feb 150) that
  the blended series lacks. Clearing the filter restored the full series.
- **AC7 — strict build.** `npm run build` (`vue-tsc -b && vite build`) → **`✓ built`**, no TS errors (only
  the pre-existing >500 kB chunk-size advisory, unrelated to this change). Re-run green after the flat-line fix.
- **AC8 — footprint.** Touched only `types.ts`, `KpiCard.vue`, `ChartCanvas.vue` (+ this spec);
  `README.md` and `.ai/CURRENT_STATE.md` untouched.

## Definition of Done
KPI cards show a chronological trend sparkline of their metric under the value/delta, driven by a
"Trend by" temporal picker, auto-seeded when the schema has a date column, cross-filter-aware, robust to
non-numeric/degenerate series, with the scalar/trend/display refetch boundaries kept tight; strict build
clean; must-not-change verified. Left in `tasks/active/` for the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴/🟠. Two 🟡 judgment calls (both reversible, flagged not silent) and the rest 🟢/ℹ️.

- 🟡 **Auto-seed trend fan-out.** Seeding `trendDimension` on every card means each KPI fires a *second*
  aggregate on mount and on every cross-filter/transform — `2N` requests for `N` cards instead of `N`.
  Chosen deliberately for Power-BI parity (a card should show its trend the instant a file lands, matching
  `seed()`'s "a dashboard exists immediately" philosophy). No correctness risk (each is seq-guarded); purely
  request volume on small demo data. Fully reversible — drop the two seed lines to make trends opt-in.
  **Recommendation: keep** for the demo; revisit if a dataset ever seeds many KPI cards at once.
- 🟡 **Earliest-200 truncation.** A temporal column with >200 distinct values returns the earliest 200
  (raw dates, `limit=200`), not bucketed — so a multi-year *daily* series would sparkline only its first
  stretch. Acceptable for MVP demo data; true `date_trunc` bucketing needs range predicates and is docked to
  **#13 date-range** (called out in "out of scope"). Not silent.
- 🟢 **Flat-series baseline (fixed during review).** A constant series first rendered pinned to the viewBox
  floor (y=22), reading like "zero". Changed to draw a **centered** horizontal line (y=`SPARK_H/2`); verified
  live — "Total rows" points went `…,22` → `…,12`, non-flat cards unchanged. Comment now matches behaviour.
- 🟢 **Trend error is swallowed by design.** A failed trend fetch (e.g. the trend column was dropped) clears
  the series so no sparkline shows; the scalar card keeps working. Intentional — the trend is decorative and
  must never break the KPI. The scalar path still surfaces its own errors.
- ℹ️ **No end-dot.** Dropped intentionally: under `preserveAspectRatio="none"` a round marker distorts to an
  ellipse. Spec text corrected to match (was stale).
- ℹ️ **`KpiConfig.trendDimension` rides into #15 persistence for free** (frontend-only view state, like
  `target`/`targetMode`) — no wire-contract change, no backend touched.
