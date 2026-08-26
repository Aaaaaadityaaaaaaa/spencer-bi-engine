# TASK-039 — Multi-table switcher: add a second table to a session + switch the active table (Wave 7 #32)

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
Wave 7 opener, backlog **#32**. The backend already fully supports **multiple tables per session** (per
ADR-006: a session's DuckDB file can hold several tables; every data/transform/history/profile/quality/export
endpoint takes an optional `?table_name`, resolved by `_resolve_table`). But the frontend had **no way to
reach that capability** — one session showed exactly one table, and there was no UI to add another or to pick
which one the app acts on. This task adds the missing frontend surface:

1. **Add another table** to the current session (calls the existing `POST /sessions/{uuid}/tables`).
2. **Switch** which loaded table the Table grid + data-prep act on.

**ADR-006 constraint honoured:** this is a *switcher only* — the app acts on **one table at a time**. No
cross-table joins, no multi-table queries; charts/Canvas stay single-table (they read the active table's
`columns`). Frontend-only. **No backend change, no wire-contract change, no new dependency, no new secret.**

## Approach & why
- **Reuse the existing endpoints; add no backend.** Adding a table is the already-present
  `POST /sessions/{uuid}/tables` (registers the upload with `is_primary=false`, refuses a duplicate table
  name). Switching is purely client state: point `state.tableName` at another already-loaded table and let the
  data layer — which already threads `table_name` through every call — refetch.
- **A `tables` list on the session singleton drives the switcher.** `useSession` now tracks
  `tables: SchemaTable[]` (the primary + any added), kept in sync from `GET /schema`. `tableName` names which
  one is active. The switcher `<select>` lists `tables`; it only renders when `tables.length > 1` (a single
  table needs no switch).
- **A switch must NOT disturb existing charts.** `dataVersion` means *"the active table's rows/schema
  changed"* and makes `ChartCanvas` re-run **every** tile. So `setActiveTable()` deliberately **does not** bump
  `dataVersion` — otherwise switching tables would silently re-point every existing chart at the new table.
  Instead the grid reloads via a **dedicated `watch(tableName)`** in `DataGrid` (decoupled from the transform
  path). Canvas/Query pick up the new `columns` reactively only for *new* tiles/queries.
- **Prefer the active table over primary after mutations / on restore.** Previously `syncAfterMutation()` and
  `restoreSession()` always reset to the primary table — which would have reverted a switch after any
  transform or a page refresh. Both now prefer the currently-active (or persisted) table, falling back to
  primary then first. This also means a transform applied to a *switched-to* table resyncs **that** table's
  schema, and a refresh returns you to the table you had switched to.
- **Surface add-errors inline.** The session error banner only renders on the empty upload screen, so a failed
  add (duplicate name, unreadable file) is shown in a small inline `addError` span in the Data Grid toolbar.

## What changed
### Frontend only — four files

**`src/types.ts`** — new response type for the existing endpoint:
- `TableUploadResponse { table_name: string; row_count: number; columns: ColumnMeta[] }` (mirrors the backend
  `TableUploadResponse` returned by `POST /sessions/{uuid}/tables`).

**`src/services/api.ts`** — the uploader:
- `uploadTable(sessionUuid, file): Promise<TableUploadResponse>` — multipart `POST /sessions/{uuid}/tables`,
  form field `file` (matches the backend `upload_table` signature). Imported `TableUploadResponse`.

**`src/composables/useSession.ts`** — the core:
- `SessionState.tables: SchemaTable[]` added (initial `[]`; cleared in `resetSession`).
- `upload()` seeds `tables` with the single primary table.
- `syncAfterMutation()` now sets `state.tables = schema.tables` and keeps the **active** table's columns
  (prefer active → primary → first) instead of always primary.
- `restoreSession()` sets `state.tables` and prefers the **persisted** table (active) → primary → first, so a
  refresh returns to the switched-to table.
- **New `setActiveTable(name)`** — no-op if unchanged/unknown; sets `tableName` + that table's `columns`,
  `persistSession()`, `refreshHistory()`. **Deliberately no `dataVersion` bump.**
- **New `addTable(file)`** — guards on `sessionUuid`/`uploading`; `uploadTable` → re-`fetchSchema` →
  `state.tables = schema.tables` → `setActiveTable(new)`; returns `true`/`false`, error via `state.error`.
- `useSession()` now exports `addTable`, `setActiveTable`.

**`src/components/DataGrid.vue`** — the toolbar UI + reload decoupling:
- Destructures `tables, uploading, error, setActiveTable, addTable` from `useSession`.
- **Switcher `<select v-if="sessionUuid && tables.length > 1" title="Switch the active table">`** in the
  header, bound `:value="tableName"`, `@change="setActiveTable(...)"`; options are `t.table_name` with a
  `(primary)` suffix on the primary.
- **"Add table" `<button v-if="sessionUuid">`** (title *"Add another table to this session"*, `Loader2` while
  `uploading` else `Plus`) that clicks a hidden `<input ref="tableFileInput" type="file"
  accept=".csv,.tsv,.parquet,.json,.xlsx" @change="onAddTableFile">`.
- `onAddTableFile` reads the file, resets `input.value` (re-pick after error), calls `addTable`, and on failure
  sets an inline `addError` span.
- **Reload decoupling** — the old `watch(dataVersion)` body was extracted to `resetToCleanWindow()` (close
  menus, clear sort/search, reload from top); it's now driven by **both** `watch(dataVersion)` (transforms)
  **and** a new `watch(tableName)` (table switch). So a switch reloads the grid onto the new table without a
  `dataVersion` bump.

No change to the backend, the wire contract, dependencies, or any other component.

## Config
**None.** No env vars, no secrets, no new client-controlled server surface (the endpoint already existed), no
new dependency, no new persisted config field beyond the already-persisted active `tableName`.

## Acceptance criteria
1. **Add a table** — with a session loaded, an **Add table** button posts a chosen file to
   `POST /sessions/{uuid}/tables` (not a new session), keeping the same session.
2. **Switcher appears at ≥2 tables** — once a session has two tables a `<select>` lists them (primary marked
   `(primary)`); it's hidden with a single table.
3. **New table becomes active** — after a successful add, the added table is selected and persisted.
4. **Switching reloads the grid** — choosing another table reloads the Data Grid onto that table's rows/columns
   and updates the persisted active `tableName`.
5. **Charts undisturbed by a switch** — switching the active table does **not** bump `dataVersion` (existing
   Canvas tiles are not re-pointed/refetched).
6. **Errors inline** — a duplicate table name (or bad file) surfaces as an inline toolbar message, not a
   silent no-op.
7. **Survives refresh + transforms** — a page refresh and a post-switch transform both stay on the
   switched-to table (not silently reverted to primary).
8. **Strict build green**; `README.md` / `.ai/CURRENT_STATE.md` untouched; no backend/wire/dependency change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user (id 7), restored session
`2a46540b…` (`spark_demo.csv`, 12 rows). Because the preview viewport is **0×0** (native file-picker and
coordinate clicks unavailable), the file input was exercised by constructing a real `File` and dispatching a
`change` on the exact input backing the **Add table** button
(`button[title="Add another table to this session"].nextElementSibling`); all assertions are synchronous
DOM / `localStorage` / network reads, which are authoritative in this env.

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 2.35s`, zero
  TS errors.**
- **Correct endpoint (not `createSession`)** — re-adding a file whose name collides with the primary produced
  a `POST /sessions/{uuid}/tables` that the backend rejected, surfaced inline as **"Table
  't_…_scores' already exists in this session"**, with the session UUID **unchanged** — proving the add path
  is `uploadTable`, and that the duplicate-name guard + inline error both work.
- **Successful add → switcher** — adding a uniquely-named `regions.csv` left the **same** session and produced
  `switcherPresent: true` with two options **`t_…_scores (primary)`** and **`t_…_regions`**; persisted
  `tableName` became `t_…_regions` (new table active + persisted); `addError: null`.
- **Switch reloads the grid** — selecting the `…_scores` option flipped the persisted `tableName` to
  `…_scores` synchronously and the grid reloaded to **`3 / 3 rows`** showing cells **Alice / Bob / Cara**
  (the `regions` values North/South/West were gone) — the dedicated `watch(tableName)` refetch, with no
  `dataVersion` bump.
- **Single-table state** — after restoring the original session, the switcher is correctly **hidden**
  (`switcherPresent: false`, one table) and the grid shows **`12 / 12 rows`** of `spark_demo`.
- **Cleanup** — the test left the app pointed back at the user's original `spark_demo` session (localStorage
  restored + reload; rehydrated to `2a46540b…`, 12/12 rows).

**Env caveat:** the 0×0 viewport means the **click-through-to-native-file-picker gesture** and the on-screen
placement/spacing of the switcher + Add-table button in the toolbar are the **user's real-browser check**. The
wiring, endpoint, switcher list/labels, active-table persistence, grid reload-on-switch, the no-`dataVersion`
guarantee, and the inline error are all exercised above and authoritative.

## Definition of Done
A session can hold more than one table from the UI: an **Add table** control uploads a secondary table via the
existing endpoint and a header **switcher** picks which loaded table the Table grid + data-prep act on, with
the choice persisted across refresh and preserved across transforms. Switching never disturbs existing Canvas
charts (no `dataVersion` bump; the grid reloads via its own `watch(tableName)`). Strict build clean;
must-not-change verified; no backend/wire/dependency change. Left in `tasks/active/` for the single sign-off.
**Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 judgment call for your sign-off; the rest 🟢 / ℹ️.

- **🟡 Toolbar filename label reflects the session's original upload, not the active table.** `fileName` is the
  session's source file (e.g. `spark_demo.csv`), and the schema carries **no per-table filename**
  (`SchemaTable` = `{table_name, is_primary, columns}`), so after switching to an added table the filename
  label doesn't change (the switcher itself keys off `table_name`, which is correct and unambiguous).
  **Your call:** leave as-is (recommended — the switcher's `table_name`/`(primary)` labels are the source of
  truth, and `fileName` legitimately denotes the session's origin file), or I can store a per-table display
  name and show the active one — a small follow-up.
- **🟢 A switch cannot re-point existing charts.** `setActiveTable` never bumps `dataVersion`; the grid reload
  is driven by a separate `watch(tableName)`. Verified live: switching `regions → scores` reloaded the grid
  (3/3 rows, Alice/Bob/Cara) with no chart refetch. This is the ADR-006 single-table-charts guarantee.
- **🟢 Active-table-aware resync fixes a latent revert bug.** `syncAfterMutation`/`restoreSession` used to
  always fall back to primary; they now prefer the active/persisted table, so a transform on a switched-to
  table resyncs that table and a refresh returns to it (not silently to primary).
- **🟢 Error paths surface, they don't swallow.** Duplicate-name (verified: *"…already exists in this
  session"*) and unreadable-file failures set an inline `addError`; `addTable` returns `false` and clears
  `uploading` in `finally`, so the button never gets stuck spinning.
- **🟢 Correct endpoint proven.** The add path issues `POST /sessions/{uuid}/tables` and keeps the same
  session UUID — not `POST /sessions` (createSession). This was the one subtlety worth nailing down, and it's
  confirmed by both the retained UUID and the backend duplicate-name rejection.
- **ℹ️ ADR-006 respected — switcher only.** No join UI, no multi-table query; Canvas/Query read the *active*
  table's `columns`. Broadening to cross-table analysis is explicitly out of scope (and a separate ADR
  decision).
- **ℹ️ `uploading` flag is shared with the initial upload.** Only one upload happens at a time, so reusing the
  flag (and the Loader2 affordance) is fine; noted for awareness.
- **ℹ️ Session-delete is a backend stub.** Throwaway sessions created while exercising the file input in the
  0×0 env can't be deleted via API and will TTL-expire from Redis; not a code issue and nothing ships from it.
