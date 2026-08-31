# TASK-017

## Title
Coercing type-cast (null-on-failure) with honest preview (Phase: Table data-prep) — an **opt-in `coerce`
flag** on the existing `cast` op that uses DuckDB `TRY_CAST` so un-parseable values become `NULL` instead
of failing the whole column. Because coercion silently discards data, the dry-run **preview is honest**: it
shows the **exact count** of currently non-null values that will be set to NULL. Default is unchanged strict
`CAST`.

## Objective
Closes the **two-step gap** that TASK-016's self-review flagged (its Low note (a)): the quality panel's
one-click **Fix** for `text_as_date` / `text_as_number` opened the cast dialog on the right column, but a
*strict* `.cast()` then failed the moment it hit the very sentinel that caused the finding (e.g. an `"N/A"`
in an otherwise-date column). The whole transform 400'd, nothing changed, and the user was told — correctly
but unhelpfully — to first null the sentinel, then cast. This feature makes that Fix a genuine **one click**:
the panel pre-seeds a *coercing* cast to the right type, and the honest preview reports exactly how many
values that will null. It is a small, **additive** change — a new optional flag defaulting to today's
behavior — reusing the `TRY_CAST` idiom already proven in `quality_service`.

## Context
The strict cast lives in `transform_service._compile_structured` (`op == "cast"`), target validated by
`_ibis_dtype(param.new_type)` (ADR-014) **before any SQL exists**. This task branches that one caster:
`col.try_cast(target)` when `coerce` is true, else `col.cast(target)` — so the compiled SQL flips
`CAST` ↔ `TRY_CAST` and the panel's "Compiled SQL" `<details>` stays truthful for free. **`try_cast` is
already in this codebase** — `quality_service.py:119-120` runs `col.try_cast("float64").count()` and
`col.try_cast("date").count()` against the live table — so no new Ibis capability is introduced. The honest
count is one extra bounded aggregate at **preview** time only:
`t.aggregate(nn=col.count(), ok=col.try_cast(target).count())` → `coerced_null_count = nn − ok` (non-null
values that fail to parse; already-null values are untouched and not counted), compiled with
`ibis.to_sql(dialect="duckdb")` and run through `db_manager.run_readwrite`. Ibis is a compiler here — it
never opens its own connection.

## Requirements
1. **Backend model** — `TransformCast` in `models/schemas.py` gains `coerce: bool = False` (default preserves
   strict behavior; the `TransformParam` discriminated union is keyed on `op` and needs no change).
   `TransformPreviewResponse` gains `coerced_null_count: Optional[int] = None` (absent/None for every
   non-coercing preview).
2. **Transform service** (`services/transform_service.py`) — cast branch chooses the caster by flag:
   `caster = t[param.column].try_cast(target) if param.coerce else t[param.column].cast(target)`. In
   `preview_transform`, after the standard result dict is built (type already validated upstream), when
   `param.op == "cast" and param.coerce`, compute `coerced_null_count` via one bounded aggregate on the
   unbound table and set it on the result. Wrapped fail-closed: any failure raises `TransformError` → 400,
   never a 500.
3. **Data layer** (`types.ts`) — `CastOp += coerce?: boolean`; `OpRequest += coerce?: boolean` **and**
   `newType?: string` (so a Fix can pre-seed the dialog's target type); `TransformPreviewResponse +=
   coerced_null_count?: number`.
4. **Dialog** (`components/OpDialog.vue`) — add `coerce: false` to the reactive `form`; the reset-watch
   seeds `form.coerce = r.coerce ?? false` and `form.newType = r.newType ?? 'VARCHAR'` (a Fix can preselect
   the type; a manual cast still defaults to VARCHAR / strict). Add a coerce checkbox in the cast branch
   (mirroring the `string_normalize` trim checkbox), labeled *"Coerce: set values that can't convert to
   {{ newType }} to NULL"*. `buildOp` emits `coerce: form.coerce`. The preview panel renders a line when
   `coerced_null_count != null` — warning-toned (reusing the imported `AlertCircle`) reading *"N value(s)
   can't be parsed as {{ newType }} and will be set to NULL."* when `> 0`, else a neutral *"All values parse
   … none will be nulled."* Auto-preview already re-fires on the built op, so toggling the checkbox
   refreshes the count.
5. **Quality panel** (`components/DataQualityPanel.vue`) — `onFix` pre-seeds a **coercing** cast for the two
   cast-mapped findings: `text_as_date → { coerce: true, newType: 'DATE' }`,
   `text_as_number → { coerce: true, newType: 'DOUBLE' }`; other codes unchanged. This is what turns the
   flagged-column Fix into a genuine one-click, honest-preview action.
6. **Strict build** — `vue-tsc -b && vite build` clean.

## Files Expected To Change
- **Backend edit:** `backend/models/schemas.py` (`TransformCast.coerce`, `TransformPreviewResponse.coerced_null_count`),
  `backend/services/transform_service.py` (caster branch + preview count).
- **Frontend edit:** `frontend/src/types.ts` (contract), `frontend/src/components/OpDialog.vue` (checkbox +
  preseed + preview line), `frontend/src/components/DataQualityPanel.vue` (`onFix` preseed — this file was
  created by TASK-016 and is still awaiting sign-off; TASK-017 edits only its `onFix`).
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; only `run_readwrite` is called.
- **`backend/routers/session.py`** — apply/preview handlers pass the body through verbatim; the new `coerce`
  field rides the existing `TransformCast` union with **no router edit**.
- **`api.ts` / `useSession.ts` / `TableView.vue`** — the op travels verbatim; `openOp(req)` assigns the
  `OpRequest` (now carrying `coerce`/`newType`) untouched.
- **`CleaningToolbar.vue`, `DataGrid.vue`** (+ its TASK-006 virtualizer), **`sql_validator.py`** — not on
  this path.
- **`README.md` / `.ai/CURRENT_STATE.md`** — sign-off + roadmap are the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **No client-assembled SQL (ADR-012).** `coerce` is a typed bool; the cast target is still validated by
  `_ibis_dtype` (ADR-014) **before any SQL exists**, and both the transform and the count aggregate are
  Ibis-compiled from server-side expressions. No client string reaches a query. `sql_validator.py` (which
  gates *AI-generated* SQL) is correctly not on this structured path.
- **Fail-closed → 400, never 500.** `TransformError → HTTP 400` at the router; the preview count block
  raises `TransformError` on any failure. A *strict* cast over a column with a stray sentinel still 400s
  with no mutation — the default behavior is byte-for-byte unchanged.
- **Single-table (ADR-006), single-writer (unchanged).** No new write path — coercion is one expression swap
  inside the existing cast op. Apply runs on non-sandboxed `run_readwrite`, protected by the temp-swap
  materialize (ADR-004): a coercing cast that somehow errored mid-apply cannot corrupt the live table.
- **Bounded work.** Exactly **one** extra aggregate query, and only for a `cast + coerce` preview; the common
  path (strict cast, every other op) is untouched. No unbounded key space.
- **Honest destructive-op UX.** Coercion nulls data, so the preview surfaces the exact count *before* Apply.
  The count is advisory (computed at preview time — a TOCTOU window shared with the sibling services, an
  already-documented Low), while the actual apply nulls exactly the un-parseable values via `TRY_CAST`.
- **No secrets, no new external calls.** Same-origin `:8000` API via the single Axios client; no API keys
  touched; the AI NL→SQL path is untouched.

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean.
2. **Default unchanged:** a cast with `coerce` off compiles `CAST(...)` and behaves exactly as today; a
   strict cast over a column with a stray sentinel still 400s (fail-closed).
3. **Coercing apply:** on a text column that is dates plus a `"N/A"` sentinel, coerce-cast to DATE → the
   un-parseable values become NULL, the rest convert; compiled SQL shows `TRY_CAST`.
4. **Honest preview:** for that same coerce-cast, the preview shows the exact null count matching an
   independent DuckDB `count(col) − count(try_cast(col …))`; toggling the checkbox off hides the count and
   shows `CAST`; a coerce-cast where everything parses shows the "none will be nulled" line (count 0).
5. **One-click Fix loop:** quality panel `text_as_date` Fix opens the dialog pre-seeded to DATE with coerce
   ON; Apply succeeds in **one** step; re-assess (dataVersion bump) drops the finding. Same for
   `text_as_number → DOUBLE`.
6. Cache backend genuine: proof prints `REDIS BACKEND IN USE: redis` (v5.0.14.1 on :6380).
7. Must-not-change: no TASK-017 fingerprint in `duckdb_manager.py` / `session.py` / `api.ts` /
   `useSession.ts` / `TableView.vue` / `CleaningToolbar.vue` / `DataGrid.vue` / `sql_validator.py`; Table
   bundle stays ECharts-free.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (Redis on 6380, backend
`:8000`, Vite `:5173`); the frozen `duckdb_manager.py` and every must-not-change file untouched by this task;
self-review with severity grades attached. **Sign-off is the user's — I do not self-close this task, nor
touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Verification (in-session, full stack live)
Two fixtures were used across the run. **Fixture A** (API-level, 6 rows — `id, when_txt, amt_txt`):
`when_txt` = 4 dates + `"N/A"` + `"unknown"`; `amt_txt` = 5 numerics + `"oops"`. **Fixture B** (full UI,
21 rows): `when_txt` = 20 dates (`2024-01-01`…`2024-01-20`) + one `"N/A"` (95.24% date-parseable);
`amt_txt` = 20 numerics + one `"oops"` (95.24% number-parseable) — tuned just over the 95% `CAST_CONFIDENT`
threshold so both quality findings fire.

- **AC-1 — strict build:** `vue-tsc -b && vite build` clean, **0 TS errors**, built in 1.80s (final state,
  after all five edits). The >500 kB chunk note is a pre-existing advisory, not an error.
- **AC-6 — cache backend genuine:** `redis_manager` reported backend **`redis`**, server **5.0.14.1** on
  **:6380** (a fakeredis fallback would print `fakeredis`); session keys present. Backend launched with
  `REDIS_PORT=6380`.
- **AC-2 — default strict unchanged (Fixture A, API):** `strict id→VARCHAR` → **HTTP 200**, compiled
  **`CAST`**, `coerced_null_count` absent. `strict when_txt→DATE` (coerce off) → **HTTP 400 fail-closed**,
  no mutation — identical to pre-TASK-017 behavior.
- **AC-3 — coercing apply (Fixture A, API):** `coerce when_txt→DATE` applied → **HTTP 200**; an independent
  post-apply row scan of `/data` counted exactly **2** NULLs (the `"N/A"` and `"unknown"`), the four real
  dates converted, and the column type became DATE. Compiled SQL showed **`TRY_CAST`**.
- **AC-4 — honest preview (Fixture A, API):** coercing previews returned the exact counts, all
  **`TRY_CAST`**: `when_txt→DATE` = **2**, `amt_txt→DOUBLE` = **1**, `id→DOUBLE` = **0** (all parse). The
  apply's independent row-scan null count (**2**) matched the preview's predicted **2** — the honest count
  is correct, not merely plausible. Flipping coerce off returned the strict `CAST` path (no count).
- **AC-5 — one-click Fix loop (Fixture B, full UI via the live browser preview):**
  - Uploaded Fixture B → session `9904ce81…`; the quality panel rendered **exactly the two expected
    findings** — *"'when_txt' looks like a date stored as text · 95.24% parse"* (medium, Cast type) and
    *"'amt_txt' looks numeric but is stored as text · 95.24% parse"* (medium, Cast type). Header: **"2 medium
    · 2 issues across 3 columns · 21 rows."**
  - Clicked the **Fix (Cast type)** on `when_txt` → `OpDialog` opened **pre-seeded**: coerce checkbox
    **checked**, target **DATE** (label read *"Coerce: set values that can't convert to **DATE** to NULL"*),
    and the auto-preview rendered **"1 value can't be parsed as DATE and will be set to NULL."** (the lone
    `"N/A"`).
  - Clicked **Apply** → network trace showed **`POST /transform/preview → 200`** then
    **`POST /transform → 200`** (a **single** step — the strict path would have 400'd here), followed by the
    dataVersion cascade `GET /schema`, `/history`, `/data`, `/quality` (re-scan), all **200**.
  - Result: the panel summary dropped **2 → 1 issue**, the **`when_txt` finding disappeared**, the `amt_txt`
    finding correctly **remained** (untouched), and the dialog closed. This is the full one-click loop the
    plan required, closing TASK-016's two-step gap.
- **AC-7 — must-not-change:** a repo-wide grep for `coerce|coerced_null_count|TASK-017` matched **only** the
  five change-set files (`schemas.py`, `transform_service.py`, `types.ts`, `OpDialog.vue`,
  `DataQualityPanel.vue`) plus three **pre-existing, unrelated** Canvas files (`ChartTile.vue`,
  `KpiCard.vue`, `aggregations.ts` — the `coerceAggregation` helper, not this cast-coerce). **No**
  must-not-change file (`duckdb_manager.py`, `session.py`, `api.ts`, `useSession.ts`, `TableView.vue`,
  `CleaningToolbar.vue`, `DataGrid.vue`, `sql_validator.py`) contains any TASK-017 token; `duckdb_manager.py`,
  `CleaningToolbar.vue`, and `sql_validator.py` are additionally byte-clean (`git diff` empty). The Table
  bundle stays **ECharts-free** — no ECharts import reached any of the five edited files (the only "ECharts"
  string on the Table path is the assertion comment in `DataQualityPanel.vue`).
- **Screenshot — not captured (environment limitation).** `preview_screenshot` timed out ("Browser pane is
  not displayed, so the page is not compositing frames"), unrelated to code or server health — the same
  limitation documented for TASK-016. All UI proof was gathered via `preview_snapshot` / DOM reads / the
  network trace (the authoritative text tools per the preview tooling), which confirmed the findings, the
  pre-seeded dialog state, the honest count line, the one-step 200 apply, and the finding's disappearance
  live.

## Self-Review (severity-graded)
Grades: Critical / High / Medium / Low / Info. **No Critical, High, or Medium defects found.** The feature is
a minimal, additive flag on an already-reviewed op: one caster branch (`try_cast` vs `cast`, the exact idiom
already live in `quality_service`), one extra bounded preview aggregate, and pure-presentation frontend
changes. The default path is byte-for-byte unchanged, and every guarantee of the strict cast (ADR-012 no
client SQL, ADR-014 validated target, ADR-004 temp-swap apply, fail-closed 400) carries over verbatim.

- **[Low] The honest count is advisory (preview-time TOCTOU).** `coerced_null_count` is computed by a
  separate aggregate at *preview* time; a transform serialized between preview and Apply could in principle
  change how many values coerce to NULL. **Why Low:** single-writer serialization + the single-user UI
  (ADR-006) make an interleaving transform practically impossible, and the *apply* itself is always exact
  (`TRY_CAST` nulls precisely the un-parseable values regardless of the earlier count). This is the same
  preview/apply window already documented as a Low in `aggregate_service`/`profile_service`/`quality_service`
  — a pattern-level property, not a regression this task introduces.
- **[Low] `OpDialog` still allows Apply on an errored dry-run preview.** Carried over from TASK-016's review:
  if a *strict* cast preview 400s, Apply remains clickable (and fail-closes 400 with no mutation). TASK-017
  does not change this `OpDialog` trait, but it materially **shrinks its blast radius** for the cast case —
  the coercing Fix no longer produces an errored preview in the first place, so the common path that used to
  hit it is gone. A future `OpDialog` task could disable Apply while the preview is in an error state.
- **[Low] A manual cast still defaults to strict (coerce off).** Only the quality-panel Fix pre-seeds
  `coerce: true`; a user hand-picking "Cast type" from the toolbar gets strict `CAST` unless they tick the
  box. **Why Low / intentional:** strict is the safer, non-destructive default — coercion silently nulls
  data, so opting in per-cast (with the honest count visible before Apply) is the correct default, and the
  checkbox is right there. Not a defect.
- **[Info] Compiled-SQL transparency is automatic.** Because the caster branch changes the *expression*, the
  preview's `compiled_sql` (and the panel's "Compiled SQL" `<details>`) shows `TRY_CAST` vs `CAST` for free —
  no separate display logic, and it can't drift from what actually runs.
- **[Info] Count semantics: non-null-only.** `coerced_null_count = count(col) − count(try_cast(col))` counts
  only currently **non-null** values that fail to parse; already-null cells are untouched by the cast and are
  deliberately not counted, so the number is exactly "how many visible values you will lose".
- **[Info] `text_as_date → DATE`, `text_as_number → DOUBLE`.** The panel pre-seeds DOUBLE (not INTEGER) for
  numbers so decimal values (e.g. `1.50`) coerce cleanly; DATE for dates. These match the `try_cast` target
  families the quality scan itself uses to raise the findings, so a finding that fired is guaranteed to have
  a ≥95%-parseable coercion target.
- **[Info] `try_cast` availability re-confirmed.** `col.try_cast(target)` compiles to DuckDB `TRY_CAST` in
  this repo's Ibis (already proven in `quality_service`), so no raw-SQL fallback was needed; the target type
  remains validated by `_ibis_dtype` before compilation either way.
- **[Info] Additive contract, backward-compatible.** `coerce` defaults to `false` and `coerced_null_count`
  defaults to `None`/absent, so existing clients and every non-cast/ non-coerce preview are unaffected;
  `TransformPreviewResponse(**result)` still validates when the key is absent.

## Status
IMPLEMENTATION COMPLETE — self-reviewed (no Critical/High/Medium). **SIGNED OFF by user on 2026-08-29.**
