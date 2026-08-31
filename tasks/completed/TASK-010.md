# TASK-010

## Title
Table v2 — data-prep workspace: collapse-on-load upload, Power BI-style transform ribbon + per-column ⋮ menus, all 10 cleaning ops via a shared preview/apply dialog, wired undo/redo (frontend-only)

## Objective
Turn the **Table** section into a real data-prep workspace. Once a dataset is uploaded the upload
dropzone **collapses to a slim bar** (freeing the view for the grid); a **transform ribbon** and
**per-column ⋮ header menus** expose all **10 cleaning ops**; each op opens **one shared dialog** that
runs a safe **dry-run preview** (row-count delta + compiled SQL) before **applying**; and the header
**Undo/Redo** buttons become live against the session's snapshot history. **No backend changes** — every
route already exists on the API (mapped by exploration); this task is the frontend that drives them.

## Context
Locked over two AskUserQuestion rounds against the user's stated vision ("once I upload a dataset the
option to upload should go and entire table just be shown and here we should have all those drop null and
all those button feature"): (1) cleaning UI = **Both** (ribbon transform buttons **and** per-column ⋮
menus — full Power BI); (2) op coverage = **all 10 ops now** (including `calculated_column`,
`filter_rows`, `string_normalize`, `dedupe_subset`). Build strategy per the user's earlier question:
**walking skeleton first** — ship the complete apply/preview/undo loop end-to-end, deepen polish later;
correctness + safety (dry-run preview, parameterized backend, no SQL string interpolation of user values)
are built in from the start, not deferred.

Baseline = commit `a3c7162` (Table/Canvas/Query Engine router shell + design-token restyle; the
"Ask AI"→"Query Engine" rename landed there). Backend API surface confirmed complete by exploration:
all cleaning/preview/undo/redo/history/schema routes exist under `/sessions/{uuid}/…`; the frontend
`api.ts` previously wrapped only `createSession`/`fetchData`. `useSession` is a module-scoped reactive
singleton (state survives navigation with zero prop wiring). Strict TS
(`noUnusedLocals`/`noUnusedParameters`/`erasableSyntaxOnly`, no path aliases → relative imports).

**Divergence note (AP-2):** the documented roadmap still lists TASK-007 (Data Grid v2 formatting) as the
"next" task; this Table-workspace build is an explicit reorder to the user's current priority. TASK-007
(type-aware cell formatting) remains earmarked and is *complementary* to this work.

## Requirements
1. **Data layer (`api.ts`, `types.ts`)** — add the transform contract types (10-op discriminated union
   `TransformOp`, `TransformResponse`, `TransformPreviewResponse`, `HistoryResponse`, `SchemaResponse`,
   `OpRequest`) and six typed wrappers: `applyTransform`, `previewTransform`, `undoTransform`,
   `redoTransform`, `fetchHistory`, `fetchSchema`. All ops POST the op object as the JSON body to a single
   `/transform` (preview twin at `/transform/preview`); optional `?table_name` only sent when set.
2. **Session actions (`useSession.ts`)** — add `applying`, `dataVersion`, `canUndo`, `canRedo`,
   `historySteps`, `fileName` state and `applyOp(op)`, `undo()`, `redo()`, `refreshHistory()`,
   `resetSession()`. After any mutation: resync row count **and live schema** (transforms add/drop/rename/
   retype columns), refresh undo/redo flags, then bump `dataVersion`. `applyOp` returns `boolean` so the
   dialog closes only on success.
3. **Grid auto-refresh (`DataGrid.vue`)** — watch `dataVersion`: reset rows/total, scroll to top, reload
   window 0. **All TASK-006 virtualizer guardrails preserved** (`PAGE=500`, `ROW_H=36`, `COL_W=160`,
   `ref="scrollEl"`, `height:440px`, `translateY`, `overscan:12`, uuid-staleness check).
4. **Per-column ⋮ menus (`DataGrid.vue`)** — each header cell gets a ⋮ button opening a **fixed-positioned**
   menu (so the grid's `overflow-auto` can't clip it) of the 6 column-scoped ops; selecting one emits
   `column-op {op, column}` to the parent. Menu dismisses on outside click / scroll / session change.
5. **Ribbon (`CleaningToolbar.vue`, new)** — grouped buttons (Nulls / Rows / Columns) covering all 10 ops;
   emits `open {op}` (no preset column → dialog shows a picker); disabled until a session exists.
6. **Shared dialog (`OpDialog.vue`, new)** — one modal driven by an `OpRequest`; renders only the active
   op's fields; **debounced auto-preview** via `/transform/preview` (row-count before→after + delta +
   collapsible compiled SQL) with a monotonic guard so stale responses can't land; Apply calls
   `applyOp` and closes on success; Escape / backdrop / Cancel close.
7. **Compact upload (`UploadDropzone.vue`)** — once `sessionUuid` is set, hide the big dropzone and show a
   slim `fileName · N rows · M columns` bar with a **Replace** action (re-opens the file picker; a new
   upload overwrites the session). File input stays mounted so Replace works from the bar.
8. **Undo/Redo (`App.vue`)** — the header buttons (previously hardcoded-disabled) bind to
   `canUndo`/`canRedo`/`applying` and call `undo`/`redo`.
9. **Strict build** — `vue-tsc -b && vite build` clean.

## Files Expected To Change (frontend only)
- **New:** `frontend/src/components/OpDialog.vue`, `frontend/src/components/CleaningToolbar.vue`.
- **Edit:** `frontend/src/types.ts` (transform contract + `OpRequest`), `frontend/src/services/api.ts`
  (6 wrappers + `tableParam`), `frontend/src/composables/useSession.ts` (transform state + actions),
  `frontend/src/components/DataGrid.vue` (`dataVersion` watch + ⋮ menus), `frontend/src/components/UploadDropzone.vue`
  (compact bar), `frontend/src/views/TableView.vue` (host ribbon + dialog), `frontend/src/App.vue` (wire undo/redo).

## Files That Must NOT Change
- **All of `backend/`** — frontend-only task; `backend/services/duckdb_manager.py` (frozen) untouched.
  Verified: `git diff --stat -- backend/` empty (§F). Cleaning routes through the API's existing
  `run_readwrite`; no backend signature touched.
- DataGrid's TASK-006 virtualizer constants + scroll logic — extended (added a `dataVersion` watch and a
  header ⋮ menu), **not** altered (§A/§D prove the second `/data` window still fires).
- ADR-012 (no string interpolation of user values into SQL) — upheld: the frontend sends op **parameters**
  as a typed JSON body; it never assembles SQL. `formula`/`predicate` are user-authored SQL *expressions*
  passed as data to the backend, which validates/compiles them (Security, §Self-Review 3).

## Security Considerations (AP-8 — name the exact path each control covers)
- **Dry-run before mutate.** Every op can be previewed via `POST /transform/preview` (`OpDialog.runPreview`),
  which the backend computes **without** materializing or bumping the schema version — the user sees the
  row-count delta and **compiled SQL** before `POST /transform` ever runs. This is the human-visible safety
  surface for destructive ops (`drop_null`, `drop_column`, `dedupe`, `filter_rows remove`).
- **No client-side SQL assembly (ADR-012).** `applyTransform`/`previewTransform` send the op as a JSON body
  (`{op:'filter_rows', predicate:'…', action:'…'}`); the frontend never string-builds a query. `formula`
  (calculated_column) and `predicate` (filter_rows) are free-text SQL *expressions* — they are forwarded as
  **data** to the backend, whose validator/compiler is the trust boundary (the backend already returns the
  `compiled_sql` we display). No new client trust boundary is introduced.
- **Optional `?table_name`.** `tableParam()` sends it only when set; otherwise the backend resolves the
  session's primary table — no client-forged table identity beyond what `POST /sessions` returned.
- **No secrets, no new external calls.** All traffic is the existing same-origin `:8000` API via the single
  Axios client. The AI NL→SQL path (LiteLLM → `sql_validator` → `run_sandboxed` → Review Gate) is **not**
  part of this task — these are deterministic, user-initiated cleaning ops.

## Acceptance Criteria
1. Strict `vue-tsc -b` build clean (10-op union types resolve; no unused imports under strict flags).
2. Upload → dropzone **collapses** to `fileName · rows · cols` bar; ribbon + full grid render; the upload
   option is gone (Replace remains).
3. Per-column ⋮ menu → op dialog opens **pre-scoped to that column**; dry-run preview shows the row-count
   delta + compiled SQL; Apply mutates and the grid auto-refreshes.
4. Ribbon button → same dialog **without** a preset column; a no-field op (`dedupe`) auto-previews.
5. `calculated_column` adds a column: preview shows **no row change**, apply grows the **column count**
   (schema resync), and the new column's values are correct.
6. Undo restores the prior state and enables Redo; applying a new op **truncates** the redo branch.
7. Console application-clean; scope = `frontend/**` + this task file only; `git diff -- backend/` empty.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live; frontend-only with the
entire backend (and `duckdb_manager.py`) unchanged; TASK-006 virtualizer behavior preserved; self-review
with severity grades attached. **Sign-off is the user's — I do not self-close this task.**

## Status
COMPLETE — **awaiting user sign-off** (not self-closed).

Proof: fresh in-session evidence with the full stack live (Redis `PONG`, backend `:8000/docs` 200, Vite
`:5173`) — strict build clean (§A); real upload → collapse-to-bar + ribbon + grid (§B); per-column ⋮ →
drop_null dry-run `5→4 (-1)` + compiled SQL → apply → `4/4` + Undo live (§C); undo→`5/5` + ribbon dedupe
`5→4` apply with redo-branch truncation (§D); calculated_column `4→4 rows` / `4→5 columns` with correct
values (§E); frontend-only scope, backend diff empty (§F).

## Proof
Captured this session via `preview_*` MCP tools against the live stack. Screenshots are unobtainable
headless (Browser pane not compositing — same limitation as TASK-008/009); verification uses
`preview_eval`/`preview_console_logs` reading real DOM state after each interaction, authoritative for
structure/behavior. The upload was driven through the **real** hidden `<input type=file>` (DataTransfer
injection → `change` event → real `POST /sessions`), so every step below is a true backend round-trip.

Test CSV (5 rows; contains one exact-duplicate row, one null `category`, one null `name`):
```
id,name,category,amount
1,Alice,A,100
1,Alice,A,100
2,Bob,,200
3,,B,
4,Carol,b,300
```

### A. Build — strict `vue-tsc` (AC1)
`npm run build` (= `vue-tsc -b && vite build`):
```
> frontend@0.0.0 build
> vue-tsc -b && vite build
vite v8.2.1 building client environment for production...
✓ 1894 modules transformed.
dist/index.html                   0.74 kB │ gzip:  0.39 kB
dist/assets/index-xlKVT94l.css   13.89 kB │ gzip:  3.88 kB
dist/assets/index-wpUiajXZ.js   205.45 kB │ gzip: 72.44 kB
✓ built in 1.49s
```
`vue-tsc -b` passed first — under strict flags this proves the 10-op discriminated union, the exhaustive
`buildOp` switch, and every wrapper's generics resolve, and no import is left unused (an earlier unused
`nextTick` was caught by `noUnusedLocals` and removed).

### B. Upload → collapse-to-bar + ribbon + grid (AC2)
After the real `POST /sessions` (body text, whitespace-collapsed):
```
… Table Undo Redo
test.csv 5 rows · 4 columns Replace
Drop nulls Fill nulls NULLS | Remove duplicates Dedupe by key Filter rows ROWS |
Add column Rename Cast type Normalize text Drop column COLUMNS
Data Grid 5 / 5 rows
id name category amount | 1 Alice A 100 | 1 Alice A 100 | 2 Bob 200 | 3 B | 4 Carol b 300
```
The big dropzone is gone (slim `test.csv 5 rows · 4 columns` bar + Replace); the ribbon shows all 10 ops
in three groups; the grid shows 5 rows including the null `category` (row 2), null `name` (row 3), and the
duplicated Alice row.

### C. Per-column ⋮ menu → drop_null → dry-run → apply (AC3)
`⋮` on the **category** header → "Drop rows with nulls" → dialog (title "Drop rows with nulls"). Preview
region read verbatim:
```
Preview (dry run) | Refresh | 5 → 4 rows (-1) | Compiled SQL | Cancel | Apply
```
Dry run correctly finds the one null-`category` row. **Apply**:
```
dialogClosed=true   rowsLabel="4 / 4 rows"   Undo.disabled=false   Redo.disabled=true
```
Grid auto-refreshed (dataVersion watch); Undo enabled from history; Redo correctly still disabled.

### D. Undo → ribbon dedupe → apply, with redo-branch truncation (AC4, AC6)
Header **Undo**:
```
afterUndo="5 / 5 rows"   Redo.disabled=false      (undo restored the row; redo now available)
```
Ribbon **Remove duplicates** (no-field op → auto-preview, no column preset):
```
title "Remove duplicate rows"   Preview: 5 → 4 rows (-1)   Compiled SQL present
```
**Apply**:
```
rowsLabel="4 / 4 rows"   dialogClosed=true   Undo.disabled=false   Redo.disabled=true
```
Applying a **new** op after an undo truncated the redo branch (Redo went `false`→`true`) — correct history
semantics.

### E. calculated_column — schema resync + correct values (AC5)
Ribbon **Add column** → `new_column_name=amount_x2`, `formula=amount * 2`. Preview:
```
4 → 4 rows (no row change)   Compiled SQL present
```
**Apply** → loaded bar and grid:
```
loadedBar: "test.csv 4 rows · 5 columns"        (column count 4 → 5 via fetchSchema resync)
grid: id name category amount amount_x2
      4 Carol b 300 600 | 2 Bob 200 400 | 1 Alice A 100 200 | 3 B …
```
`amount_x2 = amount * 2` is correct (300→600, 200→400, 100→200). This exercises the path where the
**column set** changes, not just the row count — `syncAfterMutation` re-reads the live schema and updates
`state.columns`. (Row order changed because the transform materializes a new table ordered by rowid —
expected.)

### F. Console + scope (AC7)
`preview_console_logs level=error` after the full flow: **No console logs** (application-clean).
```
$ git status --short
 M frontend/src/App.vue                       ┐
 M frontend/src/components/DataGrid.vue        │
 M frontend/src/components/UploadDropzone.vue  │  TASK-010 edits
 M frontend/src/composables/useSession.ts      │
 M frontend/src/services/api.ts                │
 M frontend/src/types.ts                        │
 M frontend/src/views/TableView.vue            ┘
?? frontend/src/components/CleaningToolbar.vue  ┐ TASK-010 new
?? frontend/src/components/OpDialog.vue         ┘
(+ tasks/active/TASK-010.md — this file)

$ git diff --stat -- backend/     → (empty)
```
Backend provably untouched; `duckdb_manager.py` in the empty backend diff.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Info — proof method] Live proof via `preview_*`; screenshots unobtainable headless.** Same
   Browser-pane non-compositing limitation as TASK-008/009. All flows verified by reading real DOM state
   after real interactions (real `POST /sessions` + real `/transform`,`/preview`,`/undo` round-trips), which
   is authoritative for behavior. `preview_eval` was used to *drive* clicks/inputs (menus + `<select>`s +
   dynamic dialog), not to implement UI.
2. **[Low — UX, verify race] Debounced auto-preview can read as the neutral "Adjust the fields…" placeholder
   for a beat.** In §E the first read landed before the 350 ms debounce + network completed; a **Refresh**
   click (same code path) immediately showed `4 → 4 rows`. Real users see it resolve on its own; the
   monotonic `previewSeq` guard prevents a stale response from overwriting a newer one. Behavior is correct;
   flagged only because the timing is observable.
3. **[Medium — security boundary, by design] `formula` and `predicate` are free-text SQL forwarded to the
   backend.** The frontend does **not** interpolate them into SQL (ADR-012 upheld) — they travel as JSON
   body fields and the backend's validator/compiler is the trust boundary (we display its returned
   `compiled_sql`). This is the intended contract, but it means client-side validation is minimal (non-empty
   only): a malformed expression surfaces as a backend error in the dialog, not a pre-flight client message.
   Acceptable for v1; richer client hints are a later polish.
4. **[Low — coverage] 5 of 10 ops exercised live** (`drop_null`, `dedupe`, `calculated_column`; preview seen
   for each; `impute_null`/`cast`/`rename_column`/`drop_column`/`string_normalize`/`dedupe_subset`/
   `filter_rows` are wired identically through the same `buildOp`→`previewTransform`/`applyOp` path but not
   each individually clicked). The shared code path + strict-typed exhaustive `buildOp` switch make the
   untested ops low-risk, but they are not *proven* here. Flagged, not hidden.
5. **[Low — UX] Undo/Redo live in the global header, enabled on every route** (Canvas/Query too), since the
   session is global. Harmless (they act on the loaded dataset), but a user on Canvas could undo a transform
   without visual feedback there. Could scope the affordance to Table later.
6. **[Low — a11y] The ⋮ menu and OpDialog are custom, not fully ARIA-annotated.** Escape + backdrop close and
   `title`s exist; no focus-trap/roving-tabindex yet. Fine for v1; accessibility hardening is a follow-up.
7. **[Info — impute custom fill] `fill_value` is sent as the raw string** from the text field; the backend
   is responsible for casting it to the column type. Consistent with the API contract; no client coercion.
8. **[Info — carried forward] `HelloWorld.vue` still dead; `@tanstack/vue-table@9` still an unused devDep.**
   Untouched by this task (flagged since TASK-006/008).
9. **[Info — sequencing] Builds on the unsigned foundation commit `a3c7162`** (TASK-008 restyle + TASK-009
   router + rename). TASK-008/009 sign-off remains the user's; this task's own diff is the 9 files in §F.

**Net:** the complete data-prep loop — upload → collapse → preview (dry run) → apply → grid refresh →
undo/redo — is proven end-to-end against the live backend with correct row/column deltas and correct
calculated values, console clean, backend and `duckdb_manager.py` provably untouched. The main honest gaps
are coverage (finding 4: 5/10 ops clicked, all sharing one verified path) and the by-design thin client-side
validation of SQL expressions (finding 3). I have **not** marked this task closed nor touched
`README.md` / `.ai/CURRENT_STATE.md` — **SIGNED OFF by user on 2026-08-29.**
