# TASK-041 — Query-result .xlsx export (Wave 2 / #24)

## Summary
The backend already implemented result-row export (`POST /sessions/{id}/export/rows`, `query.py`) and
the `exportRows()` API client, but no UI called it. Added an "Export .xlsx" button to the Query
console's "Use this result" row that downloads the currently-shown rows via the existing endpoint.

## Acceptance Criteria
- [x] After a successful query, the result row offers an `.xlsx` download of the shown rows.
- [x] Uses the existing `exportRows(sessionUuid, columns, rows)` client + backend `/export/rows`
      (which re-validates the live session and caps rows) — no new server code.
- [x] Errors surface inline (on `runError`), no crash.
- [x] Type-checks / builds clean.

## Files changed
- `frontend/src/components/QueryConsole.vue` — `exportResults()` handler + "Export .xlsx" button.

## Important implementation decisions
- Reused the pre-existing `exportRows` client. Column names are taken from `result.columns.map(c => c.name)`
  to match the backend's expected `columns` order; rows are passed verbatim from `result.rows`.
- Placed beside the existing "Save as table" / "Send to Canvas" actions (same gated `result.row_count > 0`
  block) so the three result destinations are visually grouped.

## Tests executed + actual results
Frontend `npm run build` (`vue-tsc -b && vite build`) — passes; only the pre-existing >500 kB
chunk-size warning, unrelated to this change. No automated E2E download test (no test runner wired in
`package.json`); logic reuses the already-shipped, regression-tested backend endpoint.

## Known limitations
- CSV/clipboard export of results remain client-side only (not wired to a button); "multiple tabs"
  of results is still unbuilt.
- No component test; verification is type-check/build + reuse of existing backend endpoint.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
