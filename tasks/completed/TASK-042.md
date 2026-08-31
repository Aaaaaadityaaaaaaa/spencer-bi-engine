# TASK-042 — Scatter chart type (Wave 5, #11)

## Summary
Wave 5 added the `series` 2-D breakdown to the aggregate contract (TASK-025), which unlocked
stacked/heatmap charts, but a true **scatter** (a raw point cloud over two numeric measures) was
still absent: the backend `aggregate` service only ever produced GROUP-BY shapes (KPI / 1-D series /
2-D matrix), and `ChartTile` had no scatter render branch or second-measure control. Added an
additive `measure_y` + `top_points` to `AggregateRequest`/`AggregateResponse` that, when `measure_y`
is set, returns RAW `(x, y[, group])` POINTS instead of a grouped aggregate — a backwards-compatible
contract extension (non-scatter requests are unchanged). Wired the new Y-measure picker and scatter
render into `ChartTile` and the request builder in `ChartCanvas`.

## Acceptance Criteria
- [x] Backend returns raw points when `measure_y` is set: `AggregateResponse.points` is
      `[{x, y, group?}]`, with `keys/values/matrix` empty and `aggregation: "raw"`.
- [x] Both `measure` (X) and `measure_y` (Y) must be numeric; non-numeric raises `AggregateError`
      -> HTTP 400. Optional `dimension` colours the points (the `group` field). Filters apply.
- [x] `top_points` caps the returned rows (server-clamped to 5000); `truncated` reflects the cap.
- [x] Frontend: `ChartType` includes `'scatter'`; `ChartConfig.measureY` (optional, back-compatible)
      is sent as `measure_y` + `top_points` only for scatter; ignored for all other types.
- [x] `ChartTile` shows a second "Y axis" measure picker (numeric-only) when the type is scatter, and
      a scatter ECharts option that groups points by colour column into separate series.
- [x] Empty-state / hint handling: scatter reports `points`, not `keys`, so `hasData` and `plotHint`
      were made type-aware (scatter prompts "Pick an X measure and a Y measure").

## Files changed
- `backend/models/schemas.py` — `AggregateRequest.measure_y`/`top_points`; `AggregateResponse.points`.
- `backend/services/aggregate_service.py` — `_aggregate_scatter()` (new) + early-return branch in
  `aggregate()`; fail-closed numeric + column validation.
- `frontend/src/types.ts` — `ChartType` + `'scatter'`; `supportsMeasureY()`; `ChartConfig.measureY`;
  `AggregateRequest.measure_y/top_points`; `AggregateResponse.points`.
- `frontend/src/components/ChartCanvas.vue` — request builder sends `measure_y`+`top_points` when
  `measureY` is set.
- `frontend/src/components/ChartTile.vue` — `CHART_TYPES` + scatter; `showYMeasure`/`yMeasureOptions`;
  `axisLabels` scatter case; `onMeasureYChange` + `onTypeChange` clears `measureY` off-scatter;
  scatter render branch; `hasData`/`plotHint` made scatter-aware.

## Important implementation decisions
- **Additive contract, not a new endpoint.** Reused `POST /sessions/{id}/aggregate` so no router
  change and zero impact on the existing 1-D/2-D callers. `aggregation` is ignored in scatter mode
  (the client still sends a valid value to satisfy the required field).
- **Validation reused the project's fail-closed helpers** (`_apply_filters`, `_unbound`, `_columns_of`,
  `_jsonable`, `db_manager.run_readwrite`) — no duplicated SQL assembly, no client-string-interpolated
  SQL (ADR-012).
- Points are ordered by `measure_y DESC` and capped, giving a deterministic top-N cloud.
- The Y-measure picker only offers numeric columns (`numericColumns`), matching the backend's
  requirement; switching away from scatter clears `measureY` so a stale value is never sent.

## Tests executed + actual results
Backend proof test `test_aggregate_scatter.py` (standalone, Redis-free, drives real spencer.db):

```
--- scatter x vs y (no group) ---
  [PASS] keys empty in scatter shape
  ...
  [PASS] 5 points returned
  [PASS] first point x=9.0 (order by y desc)
  [PASS] last point y=2.0 (order by y desc)
--- scatter x vs y coloured by grp ---
  [PASS] points carry a 'group' key
  [PASS] both groups present (A, B)
--- scatter top_points cap ---
  [PASS] capped to 2 points
  [PASS] truncated flag set
--- validation: numeric measures required ---
  [PASS] non-numeric measure raises AggregateError
  [PASS] non-numeric measure_y raises AggregateError
--- validation: unknown column ---
  [PASS] unknown measure raises AggregateError
RESULT: ALL CHECKS PASSED
```

Frontend `npm run build` (= `vue-tsc -b && vite build`) passes; only the pre-existing
>500 kB chunk-size warning remains (unrelated to this change).

## Known limitations
- Remaining from #11: `box` and `gauge` chart types are still unrendered (out of scope for this task).
- No automated component test for the scatter render (frontend has no test runner in `package.json`);
  verification is via type-check/build + the backend point-cloud contract test.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
