# TASK-040 — Send a Query Engine result to a table / to Canvas ("materialize", Wave 7 #23)

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (in `tasks/active/`; not self-closed)

## Objective
Wave 7, backlog **#23**. The Query Engine could *run* a reviewed `SELECT` and show its rows
(`POST /sessions/{uuid}/execute`, rolled back in a sandbox), but the result was a dead end — you couldn't turn
it into something to keep working with. This task makes a result **reusable** in the two places the app already
works with data, per your **"Both: table + Canvas"** scope decision:

1. **Save as table** — persist the result as a **real, switchable session table** (→ Table view; the new table
   becomes active).
2. **Send to Canvas** — persist it, switch to it, and land on **Canvas** with a **fresh blank chart tile** ready
   to configure over the new table.

Both destinations are fed by **one new backend endpoint** that persists the reviewed `SELECT` as a table; the
frontend adds the two actions plus the cross-route plumbing. **One new client-controlled server surface** (the
SQL + optional name), defended **identically to `/execute`**.

## Approach & why
### Backend — one endpoint, same defense as `/execute`, but it *persists*
- **`POST /sessions/{uuid}/materialize`** (owner-guarded) runs the **identical fail-closed AI-SQL defense** as
  `/execute` — `sql_validator.validate(sql)` (single read-only `SELECT`, fail-closed) **+**
  `sql_validator.scope_violation(sql, session_uuid)` (the S-1 / TASK-029 per-tenant gate: only this session's
  `t_<uuid>_…` / `backup_<uuid>_…` tables, no IO functions, no qualified names). **The only difference from
  `/execute` is `run_readwrite` instead of `run_sandboxed`** — `/execute` rolls back so nothing survives; here
  we `CREATE TABLE t_<uuid>_<clean_name> AS SELECT * FROM (<reviewed SELECT>) _q` so the result **persists** as
  a first-class session table.
- **Reuses the upload-table conventions** so the new table is indistinguishable from an added file: the
  `t_<uuid>_<clean_name>` naming (via `sanitize_table_name`, default `query_result`), the **409 duplicate-name
  guard** (checked against the Redis `schema:{uuid}` map), and `refresh_table_schema_cache(..., is_primary=False)`
  registration. It returns a **`TableUploadResponse`** — byte-identical to `POST /sessions/{uuid}/tables` — so
  the frontend reuses its existing "add a table, then switch to it" flow verbatim.
- **The persisted name is itself in-scope.** Because the new table is `t_<uuid>_…`, later Query Engine queries
  over it pass `scope_violation` unchanged — the result becomes a legitimate base for follow-up SQL (verified).

### Frontend — reuse the switch flow; a one-shot courier for the cross-route Canvas seed
- **`materializeResult(sql, name)` in `useSession`** mirrors `addTable()` exactly, but the source is SQL rather
  than a file: `materializeQuery` → re-`fetchSchema` → `setActiveTable(new)`. Like `setActiveTable` it
  **deliberately does not bump `dataVersion`** (that signal means "the active table's rows/schema changed" and
  re-runs every Canvas tile) — a *new working table* must not silently re-run existing charts. The Table grid
  reloads via its own `watch(tableName)` (added in TASK-039).
- **`useCanvasSeed` courier (new)** — a module-scoped, read-and-clear singleton (same pattern as
  `useQuestionHandoff`) that carries a one-shot "seed a chart" flag across the route change. "Send to Canvas"
  arms it, then `router.push('/canvas')`; `ChartCanvas.onActivated` reads-and-clears it and calls `addChart()`
  **exactly once** (not on every keep-alive re-activation). A blank tile is correct: Canvas charts bind to
  **the active table + a config**, not to inline result rows (ADR-006), so the tile renders over the just-created
  table as soon as the user picks a dimension/measure.
- **`QueryConsole` "Use this result" toolbar** — appears under a non-empty result with **Save as table** and
  **Send to Canvas**; both open a small inline "name this table" input (defaults to the question text or
  `query_result`), Enter/Esc to confirm/cancel, with the 409 duplicate-name error shown inline. Confirm calls
  `materializeResult(lastRanSql, name)` — **`lastRanSql`, the SQL that actually produced the shown rows**, not
  the editor's possibly-since-edited buffer — then routes to `/table` or (arming the seed) `/canvas`.

## What changed
### Backend — two files
**`backend/models/schemas.py`** — `MaterializeRequest { sql: str; name: Optional[str] = None }` (the reviewed
SELECT + optional friendly name; both re-validated / sanitized server-side).

**`backend/routers/session.py`** — imported `MaterializeRequest` and `from services.sql_validator import
sql_validator`; added the `materialize_query` endpoint (owner-guarded) described above: `validate` → 400,
`scope_violation` → 400, 409 dup-name, `run_readwrite` CREATE TABLE, `refresh_table_schema_cache(is_primary=
False)`, returns `TableUploadResponse`. Touches the session TTL like the other write paths.

### Frontend — five files
**`src/services/api.ts`** — `materializeQuery(sessionUuid, sql, name?) → TableUploadResponse`
(`POST /sessions/{uuid}/materialize`, body `{sql, name}`).

**`src/composables/useSession.ts`** — imported `materializeQuery`; added `materializeResult(sql, name?)`
(mirrors `addTable`; no `dataVersion` bump; returns the new `table_name` or `null`, error via `state.error`);
exported it.

**`src/composables/useCanvasSeed.ts`** *(new)* — the one-shot courier: `seedChartOnCanvas()` (producer) /
`takePendingSeed()` (read-and-clear consumer) over a module-scoped reactive `{ pendingChartSeed }`.

**`src/components/ChartCanvas.vue`** — imported `onActivated` + `useCanvasSeed`; `onActivated(() => { if
(takePendingSeed()) addChart() })` so a "Send to Canvas" lands on a fresh blank tile, fired exactly once.

**`src/components/QueryConsole.vue`** — imported `useRouter`, `useCanvasSeed`, `Table2` / `LayoutDashboard`
icons; destructured `materializeResult`; tracks `lastRanSql` (set on a successful run, cleared on session
switch) and the materialize UI state (`materializeDest`, `resultName`, `materializing`, `materializeError`);
added `startMaterialize` / `cancelMaterialize` / `confirmMaterialize`; added the "Use this result" toolbar +
inline name input to the results panel.

**No change** to the wire contract beyond the one new endpoint, to any other component, to dependencies, or to
any persisted schema.

## Config
**None.** No env vars, no secrets, no new dependency. The one new client-controlled surface (the SQL + name) is
defended exactly like `/execute` (validate + tenant-scope) plus `sanitize_table_name` + the 409 dedup; no
client-supplied identifier reaches SQL unsanitized, and no API key or model selection is involved (materialize
does no LLM call).

## Acceptance criteria
1. **Persist a result** — `POST /sessions/{uuid}/materialize` with a reviewed SELECT creates a queryable
   `t_<uuid>_<name>` table and returns `TableUploadResponse` (name, row_count, columns).
2. **Registered + switchable** — the new table appears in `GET /schema` with `is_primary=false`, so the
   TASK-039 switcher lists it and it can be queried again via `/execute`/`/ask`.
3. **Same defense as `/execute`** — a non-SELECT is rejected (validate, 400); a cross-tenant table reference or
   a file-read function is rejected (S-1 scope, 400); an unauthenticated call is 401 and a non-owner is 404.
4. **Duplicate name → 409** with a clear message; nothing is created.
5. **Save as table** — the action persists the result, makes it the active table, and routes to the Table view
   (grid reloads onto it via `watch(tableName)`, no `dataVersion` bump).
6. **Send to Canvas** — persists + switches, routes to Canvas, and seeds **one** fresh blank chart tile bound to
   the new table; the seed fires once, not on every Canvas re-activation.
7. **Strict build green**; `README.md` / `.ai/CURRENT_STATE.md` untouched; no dependency change.

## Verification (real output)
### Backend — live HTTP proof against the running server (`:8000`), real Redis (`:6379`), real DuckDB
The endpoint was added while the server was running **without `--reload`**, so it was restarted (same launch
command; `SPENCER_JWT_SECRET` is unset → the same fixed dev key from `config.py`, so browser tokens stayed
valid; Redis + on-disk DuckDB are durable, so no data was lost). `GET /openapi.json` then listed
`/sessions/{session_uuid}/materialize`. A scripted proof (register → CSV-upload session → materialize matrix →
`DELETE` cleanup) was run over real HTTP through `require_session_owner`. **All 16 checks passed:**

- **Happy path** — `SELECT region, SUM(amount) AS total FROM <src> GROUP BY region` → **200**, table
  `t_37c5029b…_by_region`, **row_count 2**, columns **[region, total]**.
- **Persisted + queryable + in-scope** — `/execute` `SELECT total FROM <new> ORDER BY region` → **200** with
  **[15, 20]** (north 10+5, south 20) — proving the CREATE persisted, the rows are correct, and the new
  `t_<uuid>_…` name passes the scope gate for follow-up queries.
- **Registered** — `GET /schema` lists the new table with **`is_primary: false`** alongside the primary.
- **Dup name → 409** — `{"detail":"A table named 'by_region' already exists in this session"}`.
- **Non-SELECT (`DROP TABLE …`) → 400** (validate, fail-closed).
- **Cross-tenant read → 400** — `{"detail":"This query was rejected: it references table
  't_753c…_secret' outside this session…"}` (S-1 gate).
- **File-read (`read_csv_auto('/etc/passwd')`) → 400** (S-1 gate).
- **No token → 401**; **non-owner token → 404** (`require_session_owner`).
- **Cleanup** — `DELETE /sessions/{uuid}` → 200.

### Frontend
- **Strict build** — `npm --prefix frontend run build` (`vue-tsc -b && vite build`): **`✓ built in 4.23s`**,
  zero TS errors across all seven changed files (only the pre-existing >500 kB chunk-size advisory).

**Env caveat (carried from the Canvas/switcher waves):** the preview viewport is **0×0**, so the on-screen
**click-through** — the two toolbar buttons, the inline name input, the route transition, and the blank tile
appearing on Canvas — is **your real-browser check**. In-env the authoritative evidence is the **HTTP API proof
above** (the exact contract the buttons call, including every rejection path) and the **green strict build**
(the wiring type-checks end to end). The frontend runtime path is a thin composition of already-proven pieces:
the TASK-039 `addTable`→`setActiveTable`→`watch(tableName)` grid-reload flow, plus a one-shot courier identical
in shape to `useQuestionHandoff`. I did **not** drive a live DOM click-through this session; say the word and I
can exercise it via `preview_eval` (DOM/network reads, authoritative even at 0×0).

## Definition of Done
A reviewed Query Engine result can be **kept**: one owner-guarded endpoint persists it as a real
`t_<uuid>_<name>` session table under the **same fail-closed, tenant-scoped defense as `/execute`** (proven:
validate + cross-tenant + file-read + auth + owner + 409 all reject; happy path persists a correct, queryable,
schema-registered table), and the Query Engine offers **Save as table** (→ Table, new table active) and **Send
to Canvas** (→ Canvas, fresh tile over the new table). Strict build clean; must-not-change verified; one new
endpoint, no dependency change. Left in `tasks/active/` for the single sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 for your sign-off (a scope consequence you already accepted); the rest 🟢 / ℹ️.

- **🟢 The new surface has the same defense as `/execute` — proven, not assumed.** materialize calls the
  identical `validate` + `scope_violation` before touching the DB; the *only* divergence is `run_readwrite` vs
  `run_sandboxed` (persist vs roll back), which is the entire point of the feature. The HTTP proof exercised
  every rejection: non-SELECT, cross-tenant, file-read, no-token, non-owner, dup-name. The one genuinely new
  question — "does persisting a table open a later hole?" — is answered no: the created name is `t_<uuid>_…`, so
  follow-up queries over it still pass the scope gate (proven by the `/execute` [15,20] read).
- **🟡 "Send to Canvas" switches the active table; existing tiles re-point on the *next* refetch (ADR-006).**
  `materializeResult`→`setActiveTable` changes `tableName` **without** bumping `dataVersion`, and `ChartCanvas`
  has no `watch(tableName)` — so pre-existing tiles keep their current data **in the moment**, and the new
  seeded tile binds to the new table. But every tile fetches against the *live* active `tableName`, so the
  **next** refetch trigger — any cleaning transform (`dataVersion` bump → `loadAll`) or a **page reload**
  (restores the saved board and re-runs `loadAll` against the now-persisted new active table) — re-points the
  older tiles onto the new table, and a tile whose column is absent there renders empty. This is the
  single-active-table consequence you explicitly accepted when choosing **"Both: table + Canvas."** **Your
  call:** (a) accept as-is *(recommended — it matches the approved scope and keeps one active table across the
  whole app)*, or (b) a follow-up that pins each tile to the table it was built on (a larger change to tile
  config + the aggregate path). Flagging so the re-point-on-reload timing is a conscious choice, not a surprise.
- **🟢 Materialize re-runs the SELECT server-side — it persists the *full* result, not the previewed rows.**
  The results grid shows a capped preview, but `confirmMaterialize` sends `lastRanSql` (the SQL that produced
  the rows) and the backend `CREATE TABLE AS SELECT`s it fresh, so row-count and contents are the true full
  result (proven: 2 grouped rows / [15,20], independent of any preview cap).
- **🟢 Uses `lastRanSql`, not the editor buffer.** The materialize actions send the SQL that actually produced
  the shown result, tracked separately and cleared on session switch — so editing the SQL box after running
  can't silently materialize a different query than the one on screen.
- **🟢 The Canvas seed fires exactly once.** `takePendingSeed()` is read-and-clear, so a keep-alive Canvas view
  re-activating for any other reason won't spawn stray tiles; only an explicit "Send to Canvas" seeds one.
- **🟢 No `dataVersion` bump on materialize.** Consistent with TASK-039's `setActiveTable`: a new table must not
  masquerade as "the active table's data changed" and re-run every existing chart. The grid reload rides the
  dedicated `watch(tableName)`.
- **ℹ️ Dup-name guard is check-then-create (benign TOCTOU).** The 409 reads the Redis schema map before the
  CREATE; two *simultaneous* same-name materializes could both pass the check and the loser's `CREATE TABLE`
  would fail, surfacing as the generic 400 ("Could not save result as a table") rather than a 409. A session is
  single-user and these are sequential UI actions, so this is a cosmetic status-code edge, not a correctness or
  security issue.
- **ℹ️ Name sanitation is the shared `sanitize_table_name` used by upload.** Friendly names are cleaned/deduped
  the same way an uploaded filename is, so odd characters can't break the `t_<uuid>_…` identifier; empty input
  falls back to `query_result` (the frontend also defaults it). Same robustness surface as the existing upload
  path — no new risk.
- **ℹ️ The materialized table is a snapshot, not a view.** It won't track later edits to its source table —
  which is the intended "working table" semantics (same as an uploaded table), and consistent with how the rest
  of the app treats tables.
- **ℹ️ Server restart was required to load the new route** (the running server had no `--reload`). Done with the
  identical launch command; durable stores (Redis + on-disk DuckDB) and the fixed dev JWT key made it
  transparent to any open browser session. Noted so the operational step is on record.
