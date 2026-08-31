# TASK-039 — Multi-table switcher UI (#32)

## Summary
The backend has supported multiple tables in a session since TASK-039's data layer (addTable /
materialize), and `useSession` already exposes `tables`, `setActiveTable`, `addTable` — but no
component ever rendered the switcher, so a session with 2+ tables had no way to navigate between
them from the UI. Added `TableSwitcher.vue` and mounted it in `App.vue` so it is visible on every
tab once a session holds at least one table.

## Acceptance Criteria
- [x] A bar lists every table in the active session (`state.tables`), highlighting the active one
      (`state.tableName`); clicking a chip calls `setActiveTable(name)`.
- [x] The bar is reachable from all primary tabs (Table / Canvas / Query Engine), not just Table.
- [x] "Add table" opens a file picker and uploads a secondary table via `addTable(file)`; the new
      table appears in the bar and becomes active.
- [x] Per ADR-006 the switcher only switches the single active table (no joins); switching does NOT
      bump `dataVersion` (by design in `setActiveTable`), so existing Canvas tiles keep their data
      while the grid/Canvas field lists react to the new `columns`/`tableName`.

## Files changed
- `frontend/src/components/TableSwitcher.vue` (new) — the switcher + "Add table" file input.
- `frontend/src/App.vue` — import `TableSwitcher`, mount it between the header and the content area.

## Important implementation decisions
- Placed in `App.vue` (not `TableView.vue`) so the switcher is shared across tabs; it reads the
  `useSession` singleton, so switching updates the grid, data-prep, Canvas field lists and Query
  schema uniformly and reactively.
- File accept list mirrors the backend's validated extensions: `.csv,.xlsx,.xls,.parquet,.json`.
- Hidden `<input type=file>` is reset after each pick so a failed upload can be retried with the
  same file.
- Styling reused existing App-shell tokens (`border-outline-gray-1`, `bg-surface-base`,
  `rounded-3`, `text-ink-gray-*`) to match the surrounding header.

## Tests executed + actual results
Frontend type-check + production build (the project's `npm run build` = `vue-tsc -b && vite build`):

```
> vue-tsc -b && vite build
vite v8.2.1 building client environment for production...
✓ 2754 modules transformed.
dist/assets/index-*.js ... 2,001.07 kB │ gzip: 653.55 kB
✓ built in 55.73s
```

`vue-tsc` passed (no type errors); the only output is a pre-existing >500 kB chunk-size warning,
unrelated to this change. No runtime UI test harness exists for the switcher; logic paths reuse the
already-shipped, regression-tested `setActiveTable` / `addTable` in `useSession.ts`.

## Known limitations
- No automated component test (the frontend has no test runner wired in `package.json`); verification
  is via type-check/build + reuse of existing, previously self-reviewed `useSession` mutations.
- "Add table" reuses the generic upload error surfacing (`state.error`); no inline progress beyond
  the disabled button state while `uploading`.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **Awaiting user sign-off; not self-closed.**
