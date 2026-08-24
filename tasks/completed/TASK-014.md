# TASK-014

## Title
Data grid — fix the blank band during fast scrolling (user "Bug #2"): raise the virtualizer `overscan`
so a compositor-driven fling can't outrun the rendered rows.

## Objective
The user reported: "scroll down loads 500 fine, but when I scroll up again the previous rows are blank."
Eliminate the blank viewport seen while scrolling the data grid quickly, without changing what data is
loaded, the `/data` contract, or the at-rest rendering.

## Context
Investigated live against the running stack (Vite `:5173`, backend `:8000`) by injecting a 1,200-row CSV
through the real hidden `<input type=file>` and driving the scroll container with real `scroll` events,
reading the actual DOM (each rendered row is an absolutely-positioned div with a `translateY`, so its
on-screen band is exact). Findings:

- **Not data loss.** `loadWindow` *concatenates* windows and never trims (`DataGrid.vue`), so every row
  fetched stays in memory. Confirmed rows are still present after paging.
- **Not a range-tracking defect.** With real scroll events the virtualizer tracks correctly in **both**
  directions: top → rows 1–37, middle (scrollTop 6000) → rows 143–203, bottom → rows up to 525, and the
  rendered band covers the viewport at every settled position.
- **Infinite scroll fires.** A scroll to the bottom loaded page 2 (grid label `1,000 / 1,200 rows`).

Root cause of the blank is **fast, compositor-thread scrolling**: the browser scrolls this container on
the compositor and delivers `scroll` events to the main thread late/batched. During a fast fling the
compositor shifts the already-painted layer before the virtualizer (main thread) re-renders the new
range; if the fling travels farther than the rendered band extends beyond the viewport, the viewport
paints the empty spacer until the main thread catches up. The band was `overscan: 12` rows (~430px each
side) — thin enough that a hard fling outruns it. This is why the blank only appears in motion and fills
in the instant scrolling stops, and why a synchronous test (main thread updates immediately) never
reproduces it. **Distinct from the earlier "Bug #1"** (grid blank on `<keep-alive>` return), which was
fixed separately by `onActivated(() => rowVirtualizer.measure())` and is unaffected here.

## Change
`frontend/src/components/DataGrid.vue` — raise the virtualizer `overscan` from `12` to `24` (with a
comment explaining the compositor-lag rationale). Nothing else changes: same fixed `ROW_H`, same
`getScrollElement`, same infinite-scroll watch, same concat-never-trim window logic.

Why 24 and not higher: each row is 5 short cells, so ~50–60 rendered rows stays trivially cheap, and 24
rows (~860px) each side absorbs a normal-to-fast fling's per-frame travel. Going much higher renders more
DOM, which makes each re-render *slower* and the main thread *slower to catch up* — counterproductive
past a point. 24 is a balanced 2×.

## Files Expected To Change
- **Frontend edit:** `frontend/src/components/DataGrid.vue` (the single `overscan` value + its comment).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — not on this path; backend untouched entirely
  (`git diff -- backend/` empty for this task).
- **The `/data` endpoint + its contract** — unchanged; `overscan` only affects how many already-fetched
  rows are kept in the DOM, never how many are fetched.
- **The TASK-006 window logic** (`loadWindow` concat/guards) and the Bug-#1 `onActivated` re-measure —
  both left as-is.

## Security Considerations
None. This is a pure client-side rendering-buffer size. No SQL, no new network call, no change to any
request body, no secrets. `overscan` governs only how many rows already returned by `/data` are mounted
in the DOM around the viewport (ADR-012 / AP-8 untouched — there is no trust boundary on this path).

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean.
2. At-rest coverage correct at top / middle / bottom (the rendered band spans across the viewport at
   each), with the widened buffer visibly active (rendered-row count grows from ~38 to ~61).
3. Infinite scroll still fires at the bottom (`1,000 / 1,200 rows`), and window data is still retained on
   scroll-up (no re-fetch, no blank at rest).
4. No backend diff; no change to the `/data` request/response.

## Definition Of Done
The at-rest and mechanism criteria shown as real in-session output; the in-motion blank reduction is the
*purpose* of the change but its final visual confirmation needs a real fast fling on a **visible** preview
pane (see Proof — the pane is currently hidden/non-compositing, so `requestAnimationFrame` is paused and
paint-time capture is unavailable, the same headless limitation recorded in TASK-008/009/010/011).
**Sign-off is the user's — I do not self-close this task, nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Status
COMPLETE — **signed off by the user on 2026-08-22** (confirmed the fast-scroll blank is resolved); moved
to `tasks/completed/`.

## Proof
Captured this session via `preview_*` evals against the live stack; scroll driven by real `scroll` events
on the grid container; rows read from the actual DOM `translateY`.

### A. Build — strict (AC1)
`npm run build` (= `vue-tsc -b && vite build`): `✓ 2513 modules transformed`, `✓ built in 26.03s`. The
`&&`-chained `vue-tsc -b` passed (vite would not run otherwise). The >500 kB chunk warning is the
pre-existing ECharts bundle (TASK-011 finding 3), unrelated to this change (which is a numeric literal +
comment).

### B. Overscan active + at-rest coverage (AC2)
After the change, driving real `scroll` events and reading the DOM band vs. the viewport
`[scrollTop, scrollTop+clientHeight]`:
```
top    (scrollTop 0)    -> rendered 37 rows, band [0, 1332]px,      covers viewport [0, 425]      rows 1–37
middle (scrollTop 6000) -> rendered 61 rows, band [5112, 7308]px,   covers viewport [6000, 6440]  rows 143–203
bottom (scrollTop max)  -> rendered 61 rows,                        covers viewport               rows up to 525
```
Rendered-row count rose 38 → 61 (overscan 12 → 24 confirmed live); the middle band now extends ~888px
above and ~868px below the viewport — the buffer that a fling must exceed before any blank can appear.

### C. Retention + infinite scroll intact (AC3)
Scroll to bottom loaded page 2: grid label `1,000 / 1,200 rows`, `scrollHeight` grew 18,035 → 36,035, and
the band covered the viewport at the new bottom. Scrolling back up showed the earlier rows still rendered
at rest (rows 1–37 at the top) with no re-fetch — confirming windows are retained, not dropped.

### D. Scope (AC4)
Only `DataGrid.vue`'s `overscan` value + comment changed; backend untouched.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Medium — verification gap] The in-motion blank reduction is reasoned + at-rest-verified, not
   paint-captured.** The preview pane is hidden and therefore non-compositing, so `requestAnimationFrame`
   is paused and a real fast-fling frame cannot be screenshotted (an rAF-driven probe timed out for exactly
   this reason; a `preview_screenshot` returned "the page is not compositing frames"). What *is* proven:
   the rendered band is now ~2× wider and covers the viewport at every settled position, and the mechanism
   (compositor lag vs. band extent) is well understood. Final confirmation that a hard fling no longer
   blanks needs the user's eyes on a visible pane. Flagged, not hidden.
2. **[Low — residual] `overscan: 24` (~860px) covers roughly one frame of a fast fling; an extreme
   multi-frame fling (>~1,700px/frame) could still momentarily outrun it.** Raising it further has
   diminishing returns and a real cost (more mounted rows → slower re-render → slower catch-up), so this is
   a deliberate balance, not a hard guarantee for pathological fling speeds. If the user still sees a brief
   blank on the very hardest flings, the next lever is a small render-cost reduction, not a bigger band.
3. **[Info — alternatives considered and rejected.]** Forcing a synchronous flush on every `scroll` event
   fights Vue's scheduler and would tax the main thread it's trying to unblock; `content-visibility` gives
   nothing for `translateY`-positioned rows. `overscan` is the ecosystem-standard mitigation for this
   exact symptom.
4. **[Info — relationship to Bug #1.]** Part or all of what the user saw may have been the `<keep-alive>`
   reactivation blank ("Bug #1"), already fixed via `onActivated(() => rowVirtualizer.measure())`. This
   task additionally hardens the *in-motion* path; the two fixes are independent and both remain in place.
5. **[Info — no data/contract/type impact.]** Rows are already in memory; no new fetch, no `/data` change,
   and strict TS is unaffected (a numeric literal + comment). Backend diff is empty.

**Net:** the grid's data retention, both-direction range tracking, and infinite scroll are proven correct
against the live backend; the reported blank is a fast-scroll compositor-lag artifact, mitigated by
doubling the virtualizer's overscan. Verified at-rest and at the mechanism level; the one honest gap
(finding 1) is a headless-pane limitation on capturing an in-motion frame. I have **not** marked this
closed — **awaiting your sign-off**, ideally after a quick real fast-scroll on your end.
