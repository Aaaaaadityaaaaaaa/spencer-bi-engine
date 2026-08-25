# TASK-035 — Power BI Canvas, part 3: named Save / Load dashboard slots

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
Final slice of the Power BI–style Canvas upgrade. The live board already **auto-persists** per user
(TASK-033/034), so nothing is lost on reload — but there was no way to keep **more than one** board, or
to snapshot "today's board" and come back to it. This task wires the pre-existing but **orphaned**
`useDashboards.ts` store into the Canvas header as **named Save / Load slots**:

- **Save as…** — snapshot the current multi-page board under a name (newest first).
- **Load** — replace the live board with a saved snapshot (re-runs every aggregation against whatever
  dataset is currently loaded).
- **Rename / Delete** a saved slot inline.
- **Per-user isolation** — slots are namespaced by user id, so a shared browser never leaks one user's
  saved boards to another.

This is the low-risk finale: no new dependency, no backend, no wire contract. It reuses the store that
already existed (and that TASK-034 reshaped to the multi-page snapshot shape) and the popover/inline-edit
idioms already used elsewhere in the app.

## Approach & why
- **Wire the existing store, don't rebuild it.** `useDashboards.ts` was written in Wave 6 (feature #15)
  but imported by **nothing except `useAuth`'s per-user hook** — a real orphan. TASK-034 reshaped its
  snapshot to `{ pages, activePageId }` (multi-page) while it was still orphaned, so **no single-page
  rows were ever written to disk**; `isValidSaved` therefore treats a shape-mismatched row as corrupt and
  drops it rather than attempting a migration. This task simply consumes
  `saveDashboard`/`loadDashboard`/`renameDashboard`/`deleteDashboard` from `ChartCanvas`.
- **Snapshot = the whole board (all pages).** `saveDashboard(name, { pages, activePageId })` deep-clones
  via `JSON.parse(JSON.stringify(...))`, so the saved row is **severed** from the live reactive arrays —
  a later tile edit can't mutate a saved slot, and loading can't hand back proxies that alias the current
  tiles. A saved board is portable across dataset re-uploads: it stores tile **configs + layout**, never
  fetched data, so Load re-runs the aggregations against whatever dataset is live (exactly like a saved
  SQL query in `useQueryHistory`).
- **Load mirrors the restore path.** `loadSavedDashboard` runs the same sequence as a fresh restore:
  `clearAllTileState()` → replace `pages`/`activePageId` (validating the saved `activePageId` still points
  at a real page, else fall back to the first) → `resetCountersFromPages()` (so new tiles won't collide
  with loaded ids) → `reconcilePageLayout` each page → clear the cross-filter → `persistNow()` (the loaded
  board becomes the new auto-persisted board immediately) → `loadAll()`.
- **Reused idioms, zero new UI primitives:** the Save/Load popover uses ResultsTable's
  `menuOpen` + `fixed inset-0 z-40` click-outside backdrop (no document listeners); the save-name field
  and inline slot-rename reuse the QueryConsole `savingName` inline-edit pattern (`@keydown.enter`
  confirm / `@keydown.esc` cancel). The trigger lives in the header action row, `js-export-exclude`d so
  present/export hide it.
- **Per-user for free.** The store's `k(base)` already suffixes the storage key with the active user id
  (set by `useAuth` via `loadForUser`); this task adds no new key logic.

## What changed
### Frontend (only) — no backend, no wire contract, no new dependency, no new config/secret
- **`composables/useDashboards.ts`** — reshaped single-page → **multi-page** snapshot
  (`{ pages, activePageId }`); `isValidSaved` now requires a `pages` array + `activePageId`;
  `cloneSnapshot`/`saveDashboard`/`loadDashboard` operate on the page list. (The store existed already;
  this is the shape change + the doc-comment noting it's now wired by TASK-035.)
- **`components/ChartCanvas.vue`** — consumes `useDashboards()`; adds a **Saved** header control
  (popover): a name field + Save button, and the saved-slot list with Load / inline-rename / Delete;
  `saveCurrentDashboard`, `loadSavedDashboard`, `startRenameSaved`/`confirmRenameSaved` handlers.
- **`types.ts`** — `SavedDashboard extends DashboardSnapshot` (`{ id, name, savedAt } + { pages,
  activePageId }`); reused by the store (declared under TASK-034, consumed here).

No change to `KpiCard.vue`/`ChartTile.vue`, backend, or `useAuth.ts` (its `loadForUser(useDashboards)`
call already existed from Wave 6).

## Config
**None.** No env vars, no secrets, no client-controlled server surface. `localStorage` only, per-user
namespaced (`spencer.savedDashboards:<userId>`). No new dependency.

## Acceptance criteria
1. **Save** — "Save as <name>" adds a slot (newest first); blank name is a no-op; the slot holds a
   deep-cloned copy of **all** current pages + layout.
2. **Load** — selecting a slot replaces the live board with that snapshot; every tile refetches; the
   loaded board becomes the auto-persisted board (survives a reload).
3. **Isolation from live edits** — after saving, editing/adding/removing a live tile does **not** mutate
   the saved slot; re-loading returns the board as saved.
4. **Rename / Delete** — a slot renames inline and deletes; both persist.
5. **Per-user** — a second user does not see the first user's slots (per-user storage key).
6. **Corrupt-row tolerance** — a hand-broken / shape-invalid saved row is dropped on load, not thrown on.
7. **Strict build green** — `vue-tsc -b && vite build` clean.
8. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user `uid=7`, dataset
`spark_demo.csv` (`order_date` DATE, `region` VARCHAR, `revenue` BIGINT; 12 rows).

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 2.96s`,
  zero TS errors**. (`useDashboards` consumed by `ChartCanvas` — the orphan import is gone.)
- **#1 Save (full multi-page clone)** — built a **2-page** board (Page 1: `kpi:5/6 + chart:9`; Page 2:
  `kpi:7`), Save as **"Q3 board"** → `spencer.savedDashboards:7` grew to hold the slot; the stored row's
  `pages` = 2, `activePageId` set, `savedAt` an ISO string, **id** in `<base36>-<n>` form. The stored
  copy is a **deep clone** (values, not proxies): both pages + their layout arrays present.
- **#2 Load (replaces live board + becomes auto-persisted)** — after Load, the live board matched the
  saved 2-page snapshot; a **divergent live edit made after the save** (an extra `kpi:8`) was **dropped**
  by the load; the new board was written straight to the v2 active blob (`persistNow()` in the load path),
  so it survives a reload. All aggregates on the loaded board returned **200**.
- **#3 Isolation from live edits** — after saving "Q3 board", adding `kpi:8` to the live board left the
  **saved** slot unchanged (still `kpi:5/6/chart:9` + `kpi:7`); confirms the `JSON.parse(JSON.stringify)`
  clone severed the slot from the reactive arrays.
- **#5 Per-user key** — the slot was written under `spencer.savedDashboards:7` (uid-suffixed), not the
  bare key; `loadForUser` swaps the in-memory list on user change, so a different uid starts with an empty
  list. (Store-level; a full two-user login is the real-browser check.)
- **#6 Corrupt-row tolerance** — `isValidSaved` requires `pages`+`activePageId`; a shape-invalid row is
  filtered out by `loadArray` rather than throwing (verified by the guard path; the store starts clean on
  a bad/absent value).
- **Cleanup** — the "Q3 board" slot, the divergent `kpi:8`, and the extra page were removed; the `uid=7`
  board was reset to a pristine fresh v2 seed. No lasting change to your data.

**Env caveat (carried):** the preview viewport is **0×0**, so a real two-user browser login and pointer
interaction with the popover are the **user's real-browser check**. In-env the store behavior + the
persisted `localStorage` blobs are authoritative and fully exercised above (save clones all pages, load
replaces + persists + drops divergent edits, per-user key, corrupt-row drop).

## Definition of Done
The Canvas header can Save the whole multi-page board under a name and Load it back (replacing the live
board and re-persisting it), plus rename/delete slots, all per-user; the orphaned store is now wired.
Strict build clean; must-not-change verified. Left in `tasks/active/` for the single sign-off. **Not
self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 UX judgment call for your sign-off; the rest are ℹ️/🟢.

- **🟡 Load replaces the live board with no "unsaved changes" prompt.** Load discards the current live
  board (it's already auto-persisted, but divergent edits made *since* the last save are lost — verified:
  a post-save `kpi:8` was dropped). This matches "load = switch board" (Power BI/Tableau don't prompt
  either), and the previous board is only gone if you hadn't also saved it. **Your call:** fine as-is, or
  add a "discard unsaved changes?" confirm when the live board differs from every saved slot?
- **ℹ️ Duplicate slot names are allowed.** The **id** is the identity; the name is just a label (same as
  `useQueryHistory`). Two "Q3 board" slots can coexist; rename is available if that's confusing. Chosen
  over forcing uniqueness, which would surprise on a quick re-save.
- **🟢 Saved slots are severed from the live board.** `cloneSnapshot` deep-clones via JSON round-trip
  (pages/configs/layouts are plain data — strings/numbers/null, no functions/dates), so a later tile edit
  can't mutate a saved slot and Load can't return aliasing proxies. Verified in #3.
- **🟢 Load is self-healing + collision-safe.** The load path validates the saved `activePageId`
  (falls back to page 1 if stale), `reconcilePageLayout`s every page, and `resetCountersFromPages()` so a
  tile added after a load can't reuse a loaded id. Same hardened path as a fresh restore.
- **🟢 Tolerant persistence.** `loadArray` filters via `isValidSaved` and starts clean on
  absent/corrupt/permission-denied storage; `persist` swallows quota errors (in-memory still works this
  session). Per-user `k()` namespacing is unchanged and covers isolation for free.
- **ℹ️ Starter templates (backlog #16) intentionally deferred.** The plan floated folding pre-baked
  snapshots in here; I scoped this task to Save/Load only to keep it a clean, independently sign-off-able
  slice. #16 remains a separate backlog item.
- **ℹ️ Verification mutated the live `uid=7` demo board + saved slots**, then reset them to a pristine
  seed (confirmed).
