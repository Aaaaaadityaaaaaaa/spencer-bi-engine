# TASK-040 — Multi-format table export (Wave 2 / #10)

## Summary
The backend already implemented whole-table export (`GET /sessions/{id}/export`, `query.py`) and
the encoder (`export_service.encode_table`) for csv/tsv/json/parquet/xlsx, plus a matching
`exportTable()` API client. But no UI surfaced it — only a client-side CSV path existed. Added an
`ExportMenu.vue` dropdown (CSV / TSV / JSON / Parquet / XLSX) to the Table view that downloads the
active session table via the existing endpoint.

## Acceptance Criteria
- [x] User can export the loaded table in CSV, TSV, JSON, Parquet and XLSX.
- [x] Export targets the active table (reads `tableName` from the `useSession` singleton) and scopes
      through the backend's `_resolve_table` (404 on unknown/owned mismatch) — no new server code.
- [x] Download is triggered client-side from the returned blob; errors surface inline (not a crash).
- [x] Type-checks and builds clean (reuses the existing `ExportFormat` union + `exportTable` client).

## Files changed
- `frontend/src/components/ExportMenu.vue` (new) — format dropdown + blob download.
- `frontend/src/views/TableView.vue` — mount `ExportMenu` above the quality panel (only when a session is loaded).
- `frontend/src/services/api.ts` — no change (the `exportTable` client already existed).

## Important implementation decisions
- Reused the pre-existing `exportTable(sessionUuid, format, tableName?)` client rather than adding a
  second copy (the first attempt duplicated it; removed). Typed the menu's format list as `ExportFormat[]`
  to match; pass `tableName ?? undefined` (the client takes `string | undefined`, not `| null`).
- `tableName` is read live from the singleton, so after a multi-table switch (TASK-039) the menu exports
  whichever table is currently active.

## Tests executed + actual results
Frontend `npm run build` (`vue-tsc -b && vite build`) — passes; the only output is a pre-existing
>500 kB chunk-size warning, unrelated to this change. No automated E2E test for the download (no test
runner wired in `package.json`); logic reuses the already-shipped, regression-tested backend endpoint.

## Known limitations
- Query-result rows export (#24) is still frontend-unwired: the backend `/export/rows` + `exportRows()`
  client exist, but no button calls it yet (Query view).
- No component test; verification is type-check/build + reuse of existing backend endpoint.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
