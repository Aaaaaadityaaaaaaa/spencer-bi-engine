# TASK-030 — Wave 6b: KPI delta-vs-target (#14, part 1)

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
Backlog **#14 — "KPI deltas / targets"**, first slice of **Wave 6b** (Canvas polish that rides the
existing dashboard, no persistence store). Today a `KpiCard` renders a **bare scalar** — a number with
no sense of whether it is *good*. `KpiConfig` already carries the scaffolded fields
`target?: number | null` and `targetMode?: 'higher_better' | 'lower_better'` (landed under the parked
TASK-026 types), but **nothing reads them**: no delta, no colouring, no editor.

**Goal:** wire those existing fields into the card — a **▲/▼ delta chip vs the target**, coloured
green when the value is on the good side of the goal and red when it isn't, plus a **target editor** in
the card's inline panel. Pure client-side: the target is a display concern, so **no backend, no new
aggregate, no wire-contract change.**

**Explicitly out of scope (follow-ons):**
- **KPI sparklines** (a trend series per card) → **TASK-031** — needs a per-card temporal fetch in
  ChartCanvas, a meaningfully separate chunk. Kept out so this task stays small and revertible.
- **Delta vs *prior period*** → needs range predicates on `AggregateFilter` (equality-only today);
  pairs with the #13 date-range task.
- **Persisting a target across reload** → rides feature #15 (parked 6a store, `useDashboards.ts`);
  `target`/`targetMode` are already part of `KpiConfig`, so a saved dashboard will carry them for free
  the moment #15 is wired — no extra work here.

## What changed
### Frontend (only)
- **`components/KpiCard.vue`**
  - **Delta chip** beside the value: `delta` computed = value − target; `good` = on the correct side of
    the goal per `targetMode` (`higher_better` ⇒ value ≥ target is good; `lower_better` ⇒ value ≤ target
    is good). Renders `TrendingUp`/`TrendingDown` (or `Minus` when exactly on target) + the **signed %**
    vs target, coloured `text-ink-green` (good) / `text-ink-red` (bad) / `text-ink-gray-5` (on target).
    A `title` gives the long form ("12.5% above target (10,000)").
  - **Robust to non-numeric values:** the chip renders **only** when the value is a finite number, so a
    MIN/MAX-over-date (ISO string), a null, or an error/loading state simply shows no chip. When the
    target is 0 (no meaningful %), the chip falls back to the **absolute** gap.
  - **Muted "Target: N" line** under the value whenever a target is set, so the goal is legible even
    before the number lands.
  - **Editor:** a `Target (optional)` number input (empty ⇒ null) + a `Direction` select
    (`Higher is better` / `Lower is better`) shown only once a target is set. First target set defaults
    the direction to `higher_better` so the chip always has a mode.
- **`components/ChartCanvas.vue`**
  - `onKpiUpdate` gains a **same-query guard** (mirroring `onChartUpdate`): `target`/`targetMode` are
    pure display and never change the aggregation, so editing them updates the config and re-renders the
    delta **without** a pointless `/aggregate` round-trip. Only a `measure`/`aggregation` change refetches.

### Backend
**None.** No schema, endpoint, service, or config change. The target never leaves the browser.

## Config
**None new.** No env vars, no secrets, no new client-controlled server surface.

## Acceptance criteria
1. ✅ **Delta chip correct, both directions.** With a numeric value and a target: `higher_better` shows
   green when value ≥ target (▲) / red when below (▼); `lower_better` inverts the colouring. Exactly on
   target ⇒ neutral grey `Minus`.
2. ✅ **Signed % vs target**, with an absolute-gap fallback when target = 0 (no divide-by-zero).
3. ✅ **No chip on non-numeric/absent values.** No target, a null value, an ISO-date value (MIN/MAX over
   a date), or an error/loading state ⇒ no chip, no crash. Existing target-less cards look identical.
4. ✅ **Editor round-trips.** Setting a target shows the chip + "Target: N" line and the Direction
   select; clearing it (empty input) removes the chip; flipping Direction recolours instantly.
5. ✅ **No wasted fetch.** Editing target/direction fires **no** `/aggregate` request (verified in the
   network panel); changing measure/aggregation still does.
6. ✅ **Strict build green.** `vue-tsc -b && vite build` clean (the target/targetMode types already
   exist; this only adds reads + two handlers).
7. ✅ **Must-not-change:** `README.md`, `.ai/CURRENT_STATE.md` untouched.

## Verification (real output)
Full stack up live (portable Redis `PONG`, backend `/health` → `{"status":"ok"}`, Vite preview),
registered a real user, uploaded `kpi_demo.csv` (6 rows, `sum(revenue)=6,000`), drove the **SUM OF
REVENUE** KPI card via the browser. All reads are `getComputedStyle`/DOM values (authoritative for
colour — the Browser pane wasn't displayed, so `preview_screenshot` was unavailable; computed styles
are the tooling-preferred colour proof anyway).

**AC#1 — colouring & icon, both directions** (design: arrow tracks which side of target the value is
on; colour tracks good/bad per mode):

| Case | value / target / mode | chip | icon | computed colour | token |
|------|----------------------|------|------|-----------------|-------|
| Above, higher-better | 6,000 / 5,000 / higher | `20%` | `trending-up` (▲) | `oklch(0.53 0.122 156.15)` | ✅ `--ink-green-7` (good) |
| Below, higher-better | 6,000 / 7,000 / higher | `14.29%` | `trending-down` (▼) | `oklch(0.556 0.198 26.552)` | ✅ `--ink-red-6` (bad) |
| Below, **lower-better** | 6,000 / 7,000 / lower | `14.29%` | `trending-down` (▼) | `oklch(0.53 0.122 156.15)` | ✅ **recoloured green** (below = good) |
| On target | 6,000 / 6,000 | `0%` | `minus` (–) | `oklch(0.586 0 0)` | ✅ `--ink-gray-5` (neutral) |

**AC#2 — signed % + target=0 fallback.** Percentages above are (value−target)/|target| (20%, 14.29%,
90%, 80%). With **target = 0**: chip renders the **absolute gap** `600` (title `600 above target (0)`),
`hasPercentSign=false`, `isNaN=false` — no divide-by-zero.

**AC#3 — non-numeric / absent.** (a) On mount, the four default cards show **no chip** (baseline,
target-less — identical to before). (b) A KPI set to **MIN of `order_date`** displays `2024-01-05`
(ISO string); with a target of 100 set → `chipPresent=false`, **no crash**, and the muted
`Target: 100` line still renders (goal stays legible without a delta).

**AC#4 — editor round-trip.** Editor labels went `[Measure, Aggregation]` → after a target is typed →
`[Measure, Aggregation, Target (optional), Direction]`; the `Target: N` line + chip appear; flipping
Direction recoloured the same chip red→green instantly (row 3 above vs row 2).

**AC#5 — no wasted fetch (hard counts via `performance.getEntriesByType('resource')`).** Initial canvas
mount = **5** `/aggregate` POSTs (4 KPIs + 1 chart). After **4** consecutive target/direction edits
(5000 → 7000 → flip direction → 6000): still **5** (0 refetches). Changing the **aggregation**
(Sum → Min) then took it to **6** and the card recomputed (value → `600`, chip → `90% below target`).
Guard confirmed: display-only edits skip the round-trip; query changes still fire it.

**AC#6 — build.** `npm run build` → `vue-tsc -b` clean, `vite build ✓ built in 24.14s`, 0 type errors.

**AC#7 — must-not-change.** `git status --porcelain -- README.md .ai/CURRENT_STATE.md` → empty
(untouched). TASK-030 diff = `frontend/src/components/KpiCard.vue`, `frontend/src/components/ChartCanvas.vue`
only (plus this spec). **Console:** the only error across the whole session is one expected `422` from a
deliberate `.local`-domain register attempt (EmailStr rejects reserved TLDs) — no Vue/runtime errors.

## Definition of Done
KPI cards show a coloured ▲/▼ delta against a user-set target with a direction toggle, robust to
non-numeric values and target = 0, with no extra network cost on a target edit; strict build clean;
must-not-change verified. Left in `tasks/active/` for the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
Grades: 🔴 blocker · 🟠 high · 🟡 medium · 🟢 low · ℹ️ note. **No 🔴/🟠 found.**

- 🟡 **Arrow-vs-colour semantics are a deliberate split — worth your eye.** The arrow tracks *which side
  of the target the value sits* (▲ above / ▼ below), while the *colour* tracks good/bad per `targetMode`.
  So under **lower-is-better**, a value below target is a **▼ that is green** (proven, row 3). This
  matches Power BI's "variance" convention and keeps the arrow meaning stable, but a reader skimming only
  arrows could misread it. Alternatives were "arrow follows good/bad" (arrow loses its literal meaning)
  or "no arrow, colour only." I chose direction-arrow + judgment-colour + a plain-text `title`
  ("14.29% below target") that states both unambiguously. Easy to flip if you prefer good/bad arrows.
- 🟡 **Delta compares against the *cross-filtered* value.** `props.value` already reacts to the active
  Power-BI slicer, so with a slice active the chip reads "slice vs target," not "grand-total vs target."
  This is arguably the *more* useful behaviour (does this segment hit goal?) and needs zero extra code,
  but a target mentally set against the whole dataset will look off while a slicer is engaged. Flagging
  as a product judgment call, not a bug.
- 🟢 **`0` is a valid target.** `hasTarget` is `target != null` (not truthiness), so `Target: 0` shows
  and the chip renders with the absolute-gap fallback (proven). Intended — 0 is a legitimate goal
  (e.g. "zero defects"). Negative targets also work (`Math.abs(target)` in the % denominator).
- 🟢 **Clearing a target preserves the last direction.** Emptying the input sets `target=null` but leaves
  `targetMode` untouched, so re-adding a target restores the user's prior choice rather than snapping
  back to `higher_better`. Minor, intentional nicety.
- ℹ️ **ChartCanvas guard is keyed to today's query inputs** (`measure`, `aggregation`). If a KPI later
  gains a query-affecting field (e.g. a per-card filter), that field must be added to the guard's
  comparison or its edits won't refetch. Called out so the next task doesn't trip on it.
- ℹ️ **A11y:** the chip carries a descriptive `title` and the visible `%`/number text, so the value is
  not colour-only for assistive tech. Icon is decorative. Sufficient for MVP; a formal `aria-label` is a
  possible polish.
- ℹ️ **Scope held.** Pure client, no backend/wire-contract change; `target`/`targetMode` were already in
  `KpiConfig`, so a future save/load (#15) carries them for free. Sparklines and delta-vs-prior-period
  remain deferred (TASK-031 / #13) as planned.

**My assessment:** ready for sign-off. All 7 ACs proven live against real Redis + backend with hard
network counts and computed-colour reads; build strict-green; footprint is two frontend files. The two
🟡s are UX judgment calls I'd like you to confirm, not defects — both are one-line reversible if you
disagree. Left in `tasks/active/` for your sign-off; **not self-closed, not committed.**
