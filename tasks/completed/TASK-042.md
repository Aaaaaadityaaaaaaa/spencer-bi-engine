# TASK-042 — Data-prep feedback batch (3 fixes)

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (in `tasks/active/`; not self-closed)

## Objective
Three pieces of feedback, built to touch the fewest surfaces per fix:

1. **Negative-values warning — add "remove negative sign" too.** Alongside the existing keep-≥-0 fix (which
   *drops* rows), offer **Make positive** — replace the values with their absolute value so the minus sign goes
   but **every row stays**.
2. **Column ⋮ menu must actually scroll** — a repair of TASK-041 #9. The first attempt (`max-h-[70vh]
   overflow-y-auto`) was necessary but **not sufficient**: on a tall screen the cap is measured from the viewport
   top, not the button, so a low button's menu ran off the bottom edge and — because its content was shorter than
   70vh — the scrollbar never even engaged. Now it's capped to the space actually available and flips upward when
   there's more room above.
3. **Find-and-replace "Find" gets a dropdown of the column's values** — the Normalize dialog's Find field now
   offers the column's distinct values as a typeable dropdown, so a value can be picked instead of retyped.

## Approach & why

### Backend — one new op + one new read-only endpoint (both Ibis-compiled, ADR-012)
- **#1 `absolute_value` op** (`TransformAbsoluteValue {column}`) — replaces a numeric column with `col.abs()`
  **in place** via Ibis `t.mutate(**{col: col.abs()})` (a set-based scalar op, so it compiles cleanly through the
  existing `_compile_structured` path — no raw SQL, unlike the ordered-window ops). It reuses `flag_outliers`'
  numeric-type guard: a non-numeric column **fails closed as a 400** (`"absolute_value needs a numeric column"`),
  so it can never be misapplied to text. Undoable/snapshotted like any transform. Deliberately **not** added to the
  grid's `COLUMN_OPS` list (that would offer "make positive" on text columns); it's wired **only** as the
  negatives second-fix, exactly where the feedback wanted it.
- **#1 second fix on the finding** — `QualityFinding` gained optional `alt_op` / `alt_params`. This is a *general*
  mechanism (any finding can now carry a second remedy), used here so `negative_values` advertises both
  `suggested_op = filter_rows` (keep ≥ 0, from TASK-041 #2) **and** `alt_op = absolute_value`. The scan stays
  read-only — both fixes still run through the dialog's dry-run Review Gate before anything mutates.
- **#3 `GET /sessions/{id}/column/values?column`** — distinct non-null values of one column, most-frequent first,
  for the Find dropdown. New `profile_service.distinct_values()` mirrors `profile_column`'s safe path exactly
  (fresh live-schema validation, Ibis-compiled `GROUP BY … ORDER BY count DESC LIMIT cap+1`, no client value in
  SQL). It's **bounded** (`VALUES_CAP = 500`, higher than the profiler's `TOP_N = 20` because the dropdown wants
  "all" the values of a normal categorical column) and fetches `cap+1` rows to set a **`truncated`** flag without a
  second `COUNT(DISTINCT)`. A high-cardinality column returns the top 500 + `truncated: true`; the field stays
  free-text either way.

### Frontend — the two Fix buttons, the abs op form, and the Find datalist
- **#1 second Fix button** (`DataQualityPanel.vue`) — `onFixAlt()` / `altLabel()` mirror the existing
  `onFix()` / `fixLabel()`, and a second Fix button renders `v-if="f.alt_op"` (same styling + Wrench icon) before
  Ignore. `OP_LABEL` gained `absolute_value: 'Make positive'`, so the negatives finding now shows **Filter rows**
  *and* **Make positive** side by side.
- **#1 abs op in the dialog** (`OpDialog.vue`) — an `OP_META` entry + a `buildOp` case (`absolute_value` needs
  only the shared column picker, like `dedupe` needs none), plus a short explanatory note ("drops the negative
  sign… no rows are removed"). The op appears in the dialog's column-picker op-list so the picker shows.
- **#3 Find dropdown** (`OpDialog.vue`) — a native `<datalist>` (a **typeable combobox**, so regex/free-text still
  work). A lazy `loadFindValues()` calls `fetchColumnValues` only for `string_normalize`, guarded by a monotonic
  `findSeq` (so switching column/op can't land a stale list) and re-run when the user changes the normalize
  column mid-dialog. The list attaches **only in plain (non-regex) mode** — in regex mode Find is a pattern, not a
  literal value — and a small note shows when the column was `truncated`. A fetch failure is non-fatal: the field
  degrades to plain free text.
- **#2 the real menu-scroll fix** (`DataGrid.vue`) — `menuPos` now carries `{x, y, maxH, up}`. `toggleMenu`
  measures `spaceBelow`/`spaceAbove` from the button rect, flips **up** only when the menu won't fit below *and*
  there's more room above, and sets `maxH` to the **space actually available** (min 160px). A `menuStyle` computed
  pins the menu by `top` **or** `bottom` accordingly and sets `maxHeight` inline. The container's flat
  `max-h-[70vh]` is gone; `overflow-y-auto` now engages against a real, anchor-relative cap, so the menu is always
  on-screen and scrolls whenever it's taller than the space it has.

## What changed
### Backend — five files
- **`backend/models/schemas.py`** — new `TransformAbsoluteValue` (+ added to the `TransformParam` union);
  `QualityFinding.alt_op` / `alt_params`; new `ColumnValues` response model.
- **`backend/services/transform_service.py`** — `absolute_value` branch in `_compile_structured` (numeric guard +
  `t.mutate(col=col.abs())`).
- **`backend/services/quality_service.py`** — `_finding()` gained `alt_op`/`alt_params`; `negative_values` now
  carries `alt_op = absolute_value` and its detail text mentions the second option.
- **`backend/services/profile_service.py`** — `VALUES_CAP = 500` + new `distinct_values()`.
- **`backend/routers/query.py`** — `GET /{session_uuid}/column/values` → `ColumnValues` (imported the model).

### Frontend — four files
- **`src/types.ts`** — `AbsoluteValueOp` (+ union); `QualityFinding.alt_op` / `alt_params`; `ColumnValues`.
- **`src/services/api.ts`** — `fetchColumnValues()`.
- **`src/components/OpDialog.vue`** — `absolute_value` `OP_META` + `buildOp` case + explanatory note + column-picker
  op-list entry; `findValues` / `findTruncated` state, `loadFindValues()`, the Find `<datalist>` + truncation note.
- **`src/components/DataQualityPanel.vue`** — `OP_LABEL.absolute_value`; `onFixAlt()` / `altLabel()`; the second
  Fix button.
- **`src/components/DataGrid.vue`** — `menuPos {x,y,maxH,up}`, rewritten `toggleMenu`, `menuStyle` computed, and the
  menu container switched from `max-h-[70vh]` to the dynamic style.

## Config
**None.** No env vars, no secrets, no new dependency, no persisted-schema change. `absolute_value` adds no
client-controlled SQL text (column validated against the live schema, numeric-guarded, Ibis-compiled);
`/column/values` is read-only and takes only a schema-validated column name. No LLM / API-key surface is touched.

## Acceptance criteria
1. **#1** — the `negative_values` finding shows **two** fixes: *Filter rows* (keep ≥ 0, drops rows) and *Make
   positive* (abs, keeps every row). Applying *Make positive* leaves the row count unchanged and removes the sign.
2. **#1 guard** — `absolute_value` on a non-numeric column fails as a 400, never mutates.
3. **#3** — in the Normalize dialog, the Find field (plain mode) offers the column's distinct values as a dropdown;
   picking one fills Find; free-text and regex mode still work; a high-cardinality column shows the "most common
   only" note.
4. **#2** — a column ⋮ menu opened from a button low in the window stays fully on-screen (flips up) and, when
   taller than the space it has, **scrolls**.
5. **Strict build green**; `README.md` / `.ai/CURRENT_STATE.md` untouched; no dependency change.

## Verification (real output)
### Backend — live HTTP proof against the running server (`:8000`), real Redis (`:6379`), real DuckDB
The new op + endpoint were added while the server ran **without `--reload`**, so it was restarted (same launch
command, same fixed dev JWT — Redis + on-disk DuckDB durable, so no data lost). Health returned 200 with no import
error. A scripted proof (register → upload an 8-row CSV with a signed `amount` + repeated categoricals) ran over
real HTTP through `require_session_owner`. **All checks passed:**

- **#1 finding carries the second fix** — `GET /quality`: the `negative_values` finding on `amount` reports
  `suggested_op = filter_rows` **and** `alt_op = absolute_value`.
- **#1 abs preview** — `POST /transform/preview {absolute_value, amount}`: `8 → 8` rows, `delta 0`; compiled SQL is
  `SELECT ABS("t0"."amount") AS "amount", …` (Ibis-compiled, ADR-012).
- **#1 abs apply** — `POST /transform`: HTTP 200; reading the column back, `amount = [50,100,25,200,10,30,5,75]`
  (**all positive, no row lost**, total still 8).
- **#1 guard** — `absolute_value` on the VARCHAR `category` → **HTTP 400**
  `"absolute_value needs a numeric column; 'category' is VARCHAR"`.
- **#3 values endpoint** — `GET /column/values?column=category` → `{"values":["A","B","C"],"distinct":3,
  "truncated":false}` (most-frequent first); same shape for `city`; a bogus column → **HTTP 400**
  `"column 'nope' not found"`.

### Frontend
- **Strict build** — `npm --prefix frontend run build` (`vue-tsc -b && vite build`): **`✓ built in 2.99s`**, zero
  TS errors across all changed files (only the pre-existing >500 kB chunk-size advisory).
- **#2 menu algorithm** — the preview viewport is **0×0** (carried env constraint: `window.innerHeight` reads 0 and
  `preview_resize` can't grow it), so a live *pixel* render of the menu is **your real-browser check**. In-env I
  verified the **positioning math itself** by evaluating `toggleMenu`'s exact formula against realistic synthetic
  viewports:
  - *tall screen (900px), button near the bottom (y≈840)* → **flips up**, `maxH 808`, the menu renders
    `top 336 → bottom 816`, **fully on-screen** (the old 70vh cap would have run to 1474px, off-screen, with no
    scrollbar).
  - *short screen (430px), mid button* → stays down, `maxH` capped to **208**, 480px content **scrolls** and stays
    on-screen (`top 214 → bottom 422`). This is the case where `overflow-y-auto` now actually engages.
  - *tall screen, high button* → stays down, fits without scrolling.

## Definition of Done
Three feedback items implemented with the smallest viable surface each: one new numeric-guarded, Ibis-compiled op
+ one bounded read-only endpoint (both proven by live HTTP), and four frontend files proven by a clean strict
build (plus an algorithm simulation for the menu geometry the 0×0 viewport can't render). `absolute_value` adds no
unsanitized SQL surface. Must-not-change files untouched; no dependency change. Left in `tasks/active/` for the
single sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. The menu repair carries one honesty note (🟡) about how it was verified; the rest 🟢 / ℹ️.

- **🟡 #2 menu fix verified by build + geometry simulation, not a live pixel render.** The reported "still not
  scrollable" was real: TASK-041 #9's `max-h-[70vh]` capped against the viewport, not the anchor, so a low button's
  menu overflowed the bottom while never triggering its own scrollbar (content < 70vh). The rewrite caps to the
  measured space and flips up, and the exact formula was proven on-screen/scrolling across three viewport
  scenarios — but the **0×0 headless viewport can't render the actual menu**, so the final pixel confirmation is
  **your real-browser check**. Flagging that this is the *second* attempt at this item, now with the root cause
  fixed rather than the symptom re-patched. **Recommended: accept** — the geometry is proven and the build is
  green; I'd rather be explicit than claim a screenshot I can't take.
- **🟢 #1 abs is a real, safe, undoable transform, wired exactly where asked.** Proven end-to-end (preview 8→8,
  apply flips the signs with no row loss, VARCHAR fails closed as 400). It's offered **only** as the negatives
  second-fix (not in the grid's column menu), so "make positive" can't be misapplied to a text column, and it
  snapshots/records history like any op so undo covers it.
- **🟢 #1 the two-fix mechanism is general, not a one-off.** `alt_op`/`alt_params` live on the finding model and the
  panel renders a second button for **any** finding that carries one — so a future finding can offer an
  alternative remedy with no further UI work. Here only `negative_values` uses it.
- **🟢 #3 Find dropdown is a convenience layer that never breaks the field.** It's a native `<datalist>` (typeable),
  attaches only in non-regex mode, is monotonic-guarded against stale results, and degrades to plain free text on a
  fetch error — so regex, arbitrary text, and offline all still work.
- **ℹ️ #3 the values list is bounded at 500 + `truncated`.** "List all the unique values" is honoured for a normal
  categorical column; a very high-cardinality column returns the 500 most common with a visible "most common only"
  note (the field stays free-text). The cap keeps the payload bounded; raise `VALUES_CAP` if you want a larger
  list.
- **ℹ️ Server restart was required** to load the new op + endpoint (no `--reload`). Done with the identical launch
  command; durable Redis + on-disk DuckDB and the fixed dev JWT kept it transparent to any open browser session.
- **ℹ️ Working tree also carries TASK-040 (#23 materialize) and TASK-041**, both still awaiting your `mv`
  sign-off; this task's edits are additive and don't touch theirs.
