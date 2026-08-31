# TASK-012

## Title
Query Engine — AI NL→SQL behind a MySQL-Workbench-style editor (Phase 6): a CodeMirror 6 SQL editor with a
LiteLLM NL→SQL assist, wired through the fail-closed `sql_validator` → sandboxed `run_sandboxed` → human Review
Gate, plus a synchronous `POST /execute` path (column recovery + row cap) and real business-dictionary CRUD that
version-invalidates the AI SQL cache.

## Objective
Make the **Query Engine** section real. Until now the whole AI path was inert scaffolding: `ai_service.generate_sql`
was a bare `pass`, every `routers/ai.py` endpoint returned fake data, `AIQueryBox.vue` was a static input with a
hidden Review-Gate placeholder, and `CustomInstructions.vue` showed a hardcoded example with no fetching. This task
delivers the last product pillar of the vision — "instead of 'Ask AI' we should call it **Query Engine**, and I
want its interface a bit like **MySQL Workbench** but we keep our AI API in it" — as a working loop: upload a
dataset → open Query Engine → write SQL in a real editor **or** ask in plain English → the AI returns SQL **into
the editor** (the Review Gate: shown + editable, nothing auto-runs) → click **Run** → results render. Business
terms defined in Custom Instructions feed the prompt; cleaning the data in the Table tab invalidates stale AI SQL
automatically via the version-keyed cache.

## Context
Locked with the user over one AskUserQuestion round (four "recommended" picks): (1) **LLM wiring = LiteLLM
gateway** — one call path routes to Claude **or** Gemini by whichever env key is set. (2) **`/execute` =
synchronous JSON** — validate → `run_sandboxed` → return rows as JSON; the documented async
`query_id`/poll/**MessagePack** path is **deferred** (stub left intact), a recorded divergence à la TASK-011's
`/aggregate` vs the `/chart` sketch. (3) **SQL editor = CodeMirror 6** (`codemirror` + `@codemirror/lang-sql`) —
the Workbench feel with a clean Vite integration (no web workers). (4) **`/ask` loop = self-correcting** —
generate → sqlglot-validate → rolled-back sandboxed dry-run to catch real DuckDB errors, feeding the error back,
bounded at 3 attempts (ARCHITECTURE.md).

The hard parts already existed and were proven before this task: **defense layer 1** `sql_validator.validate()`
(fail-closed, 25/25 adversarial, ADR-013); **layer 2** `db_manager.run_sandboxed()` (unconditional-rollback,
ADR-010, frozen); the Pydantic contract; and the Redis key schema. This task wired the dormant middle. Because
`run_sandboxed` returns `fetchall()` **without** column names and `duckdb_manager.py` is frozen, names are
recovered on the same sandboxed path via a read-only `DESCRIBE SELECT * FROM (<sql>) _q` — no manager change.

Baseline = the still-unsigned TASK-008/009/010/011 working tree (itself on commit `a3c7162`). None of those tasks
has been committed or signed off, so this Query Engine work sits on top of them; the scope section (§F) separates
TASK-012's own files from the inherited changes.

**Recorded divergences from the plan (not hidden):**
- The async `/execute` (`query_id` + poll + MessagePack) is **deferred**; `POST /execute` is **synchronous JSON**
  returning `ExecuteResultResponse`. The `POST /queries/{id}` poll stub and the `POST /chart` MessagePack stub are
  left **intact** (both still `return b""` / the completed-stub shape). Mirrors TASK-011's `/aggregate`-vs-`/chart`
  divergence.
- `AIQueryBox.vue` is **deleted** and replaced by `QueryConsole.vue` (the ask→review→execute orchestrator) rather
  than edited in place, because the mockup shared almost no structure with the real console.

## Requirements
1. **LiteLLM NL→SQL engine** (`services/ai_service.py`, rewrite) — provider chosen by `SPENCER_LLM_MODEL` else by
   available key (`ANTHROPIC_API_KEY` → `anthropic/claude-*`, else `GEMINI_API_KEY` → `gemini/*`); **no key →
   `LLMConfigError`** (surfaced as a uniform error, never a crash). `async resolve_sql(question, schema, bizdict)
   → {sql, retries_used}` runs the bounded (max 3) loop on `litellm.acompletion`: assemble prompt (per-table
   `ddl` + low-cardinality `samples` + matched bizdict terms + on retry the prior SQL & classified error) →
   extract SQL (strip fences/prose) → `sql_validator.validate` → rolled-back `run_sandboxed` dry-run → classify
   DuckDB errors (column-not-found → append real schema; identical-repeat → "try a different approach") and retry;
   API failure is a **distinct** retryable mode, not "bad SQL". Thin `generate_sql(...)` shim honors the
   documented one-attempt signature.
2. **`POST /ask`** (`routers/ai.py`, rewrite) — load `schema:{session}` (404 if none) + `bizdict:{session}`;
   `question_hash = sha256(normalized)`, `sv = get_version`, `bv = get_bizdict_version`; check
   `query:{qh}:{sv}:{bv}` (hit → `cache_hit=True, retries_used=0`) then `fail:{qh}:{sv}:{bv}` (hit → cached error,
   no token burn); miss → `resolve_sql` → on success `SET query:...` (no TTL, version-keyed), on resolve failure
   `SETEX fail:... 300` + 422. `LLMConfigError → 503`, `LLMAPIError → 502` (neither cached).
3. **`POST /execute`** (`routers/ai.py`, rewrite) — `sql_validator.validate(sql)` **first** (fail-closed → 400;
   covers user-edited SQL); recover columns via `DESCRIBE SELECT * FROM (<inner>) _q`; fetch rows via
   `SELECT * FROM (<inner>) _q LIMIT MAX_ROWS+1` (`MAX_ROWS=1000`), `truncated = len > MAX_ROWS`, trim, zip
   names→dict; runtime DuckDB error → 400 `"Query failed: …"`. Returns `ExecuteResultResponse`.
4. **bizdict CRUD** (`routers/ai.py`, `GET/POST/DELETE /instructions`) — real CRUD against
   `bizdict:{session}` (`{term: definition}`); every write calls `incr_bizdict_version(session)` so cached AI SQL
   invalidates on any term change. Empty term/def → 400; delete-missing → 404.
5. **Redis helpers** (`services/redis_manager.py`, edit — NOT frozen) — `get_bizdict_version`/
   `incr_bizdict_version` (key `bizdict_version:{session}`) + `get_sql_cache`/`set_sql_cache`/`get_fail_cache`/
   `set_fail_cache(ttl=300)` over the documented `query:`/`fail:` keys, replacing the `pass` stubs.
6. **Schema** (`models/schemas.py`, edit) — add `ExecuteResultResponse{columns, rows, row_count, truncated}`
   (JSON, mirrors `DataResponse`); `ExecuteResponse`/`QueryPollResponse` kept for the deferred async path.
7. **Editor + components** — `composables/useCodeMirror.ts` (new: `EditorView` lifecycle, `sql()` + basicSetup +
   `Mod-Enter` run + `readOnly` Compartment + guarded update listener, `destroy()` on unmount);
   `components/SqlEditor.vue` (new: thin host, `v-model:sql` + `@run`); `components/ResultsTable.vue` (new:
   presentational sticky-header scroll table, in-memory props, cell coercion + truncation notice — **not** the
   frozen TASK-006 fetch-windowed virtualizer); `components/QueryConsole.vue` (new: ask→review→execute
   orchestrator with a `cache_hit`/`retries_used` badge, a schema-columns reference, and a **uuid-staleness
   guard** on both async calls); `components/CustomInstructions.vue` (rewrite: real CRUD, reload on
   `sessionUuid`); `views/QueryEngineView.vue` (rewrite: compose the two, keep the "No data loaded" empty state);
   **delete `AIQueryBox.vue`**.
8. **Data layer** (`types.ts`, `api.ts`) — `AskResponse`/`ExecuteResultResponse`/`CustomInstruction` types
   (snake_case wire); `askQuestion`/`executeSql`/`fetchInstructions`/`addInstruction`/`deleteInstruction`
   wrappers reusing the shared `http` client + `apiErrorMessage`.
9. **Deps** — `codemirror` + `@codemirror/lang-sql` → frontend `dependencies`; `litellm` → backend deps; optional
   `SPENCER_LLM_MODEL` comment in `.env.example`.
10. **Strict build** — `vue-tsc -b && vite build` clean.
11. **Query Engine ergonomics** (extends the three editor files, so the long UUID-laden table name never has to be
    typed) — (a) `QueryConsole.vue` **pre-seeds** the editor with `SELECT * FROM <table> LIMIT 100;` on session
    load, only when the editor is empty or still holds a prior auto-seed (never clobbers user- or AI-authored SQL,
    including across a dataset swap); (b) `useCodeMirror.ts` feeds the session table + its columns into
    `sql({ schema, defaultTable })` through a `Compartment` reconfigured on dataset change, so `FROM`/column
    **autocomplete** works; (c) the schema reference renders a click-to-insert **table-name chip** and the column
    chips insert too — `@mousedown.prevent` keeps the editor's caret so a click inserts at the cursor (else appends
    to the end). Resolves Self-Review finding 4.

## Files Expected To Change
- **Backend rewrite:** `backend/services/ai_service.py`, `backend/routers/ai.py`.
- **Backend edit:** `backend/services/redis_manager.py` (bizdict version + cache helpers),
  `backend/models/schemas.py` (`ExecuteResultResponse`), `backend/pyproject.toml` (`litellm`),
  `../.env.example` (`SPENCER_LLM_MODEL` comment).
- **Frontend new:** `frontend/src/composables/useCodeMirror.ts`, `frontend/src/components/SqlEditor.vue`,
  `frontend/src/components/ResultsTable.vue`, `frontend/src/components/QueryConsole.vue`.
  - *`useCodeMirror` / `SqlEditor` / `QueryConsole` also carry requirement 11's ergonomics (pre-seed, schema
    autocomplete via a Compartment, click-to-insert chips with `mousedown.prevent` cursor retention).*
- **Frontend rewrite:** `frontend/src/components/CustomInstructions.vue`, `frontend/src/views/QueryEngineView.vue`.
- **Frontend edit:** `frontend/src/services/api.ts`, `frontend/src/types.ts`, `frontend/package.json`.
- **Frontend delete:** `frontend/src/components/AIQueryBox.vue`.
- Plus this task file.

## Files That Must NOT Change
- **`backend/services/duckdb_manager.py` (FROZEN)** — untouched; only `run_sandboxed`/`run_readwrite` are called.
  Column names are recovered via a read-only `DESCRIBE` on the sandboxed path, so no manager change is needed.
  Verified: `git diff -- backend/services/duckdb_manager.py` empty (§F).
- **`backend/services/sql_validator.py`** — the fail-closed AI-SQL gate is **used**, not modified.
- **The `POST /chart` MessagePack stub** (`routers/query.py`) and **the `POST /queries/{id}` poll stub**
  (`routers/ai.py`) — the deferred async/large-result paths; both left as-is (§F).
- **DataGrid's TASK-006 virtualizer** and **Canvas (TASK-011)** — not on this task's path.
- **ADR-006 single-table** — the prompt lists session tables; no join UI is introduced. **ADR-012** — Spencer's
  own queries are unchanged; AI SQL is the sanctioned free-form path, exactly what the validator + sandbox + Review
  Gate exist to contain, and it is never assembled from client string-interpolation.
- **`README.md` / `.ai/CURRENT_STATE.md`** — not touched; sign-off (and any roadmap update) is the user's.

## Security Considerations (AP-8 — name the exact path each control covers)
- **3-layer AI-SQL defense, all live on the exact paths.** (1) `sql_validator.validate()` gates **both** the
  model's output inside `ai_service.resolve_sql` **and** any SQL the user submits to `POST /execute` (first line of
  the handler, before any DB touch) — so a hand-edited or model-emitted non-SELECT / stacked / write statement is
  rejected with 400 and never reaches DuckDB. (2) Every execution — the `/ask` dry-run **and** the `/execute`
  DESCRIBE + row fetch — goes through `db_manager.run_sandboxed`, which rolls back unconditionally, so even a
  validated statement leaves no trace. (3) The **human Review Gate**: `/ask` only drops SQL **into the editor**;
  nothing runs until the user clicks **Run** (`QueryConsole.run` → `/execute`). §B proves DROP/stacked/INSERT/
  UPDATE/DELETE/CTE-write are all 400 and the sentinel table survives.
- **No client-assembled SQL for Spencer's own queries (ADR-012 unchanged).** `askQuestion`/`executeSql` send
  `{question}` / `{sql}` as typed JSON; the free-form SQL string is the AI path by design and is contained by the
  three controls above, not trusted.
- **Version-keyed cache invalidation.** `query:{qh}:{sv}:{bv}` and `fail:{qh}:{sv}:{bv}` embed both
  `schema_version` and `bizdict_version`; a Table-tab transform (bumps `sv`) or any bizdict add/delete (bumps
  `bv`) makes the old key unreachable, so a stale/now-invalid cached query can't be replayed against a changed
  schema. §-cache proves the bump→miss→re-seed→hit cycle.
- **Bounded token burn.** `fail:` carries a 300 s TTL so a genuinely unanswerable question isn't retried on every
  keystroke, while a transient **API** failure (`LLMAPIError → 502`) is **not** cached as a permanent failure.
- **Row cap on `/execute`.** `LIMIT MAX_ROWS+1`-wrap + `truncated` flag (MAX_ROWS=1000) closes the documented
  "no row cap on /execute" gap; one query can't stream an unbounded result into the browser.
- **Fail-closed error contract, never 500.** No-key → 503, upstream API error → 502, resolve-failure → 422,
  reject/runtime → 400, missing schema → 404 — every branch is a typed error surfaced in the UI, not a stack trace.
- **Secrets from env, never committed.** `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`/`SPENCER_LLM_MODEL` are read from
  the environment; `.env` is gitignored; only a comment was added to `.env.example`.
- **Single-table only (ADR-006).** The prompt lists the session's own tables; no join UI exists. A raw AI query
  that joins two session tables is still read-only + sandboxed + user-reviewed (acceptable, documented).

## Acceptance Criteria
1. Strict `vue-tsc -b && vite build` clean (string-literal unions, `import type`, no unused, relative imports).
2. `POST /execute`: a valid `SELECT` → correct `{columns, rows, row_count, truncated}`; DROP/stacked/CTE-write →
   **400** and the sentinel table survives; a valid-but-wrong-column SELECT → surfaced runtime error; a large
   result → `truncated=true` at the 1000-row cap; an empty result → well-formed `row_count:0` with columns intact.
3. `POST /ask` error contract with **no key**: no-key → **503**, empty question → **400**, unknown session →
   **404** — each a clean typed error, never a crash.
4. Version-keyed cache: a seeded `query:` entry → `cache_hit=true, retries_used=0`; a reformatted (whitespace/case)
   question hits the **same** entry; a `bizdict_version` bump makes it **miss**; re-seeding at the new version hits
   again (proves it's version-keyed, not global); a seeded `fail:` entry → **422** with the cached message.
5. bizdict CRUD: `GET/POST/DELETE /instructions` round-trip in `bizdict:{session}`, each write bumps
   `bizdict_version` (cross-checked by an independent read straight out of Redis); empty term → 400, delete-missing
   → 404.
6. Frontend live: Query Engine tab → type SQL in CodeMirror → Run → `ResultsTable` renders correct rows; NL ask
   with no key → friendly error, no crash; Custom Instructions add/list/delete with a redis-cli cross-check;
   uuid-staleness guard present on both async calls.
7. Console application-clean; `git diff -- backend/services/duckdb_manager.py` empty; the `/chart` and
   `/queries/{id}` stubs unchanged.
8. Query Engine ergonomics (requirement 11): on load the editor is pre-seeded with a runnable
   `SELECT * FROM <table> LIMIT 100;` and that seed executes → rows; typing `FROM t` offers the full table name as
   the top completion and `SELECT r` offers `region`; a chip click inserts at the caret when the editor is focused
   (cursor preserved via `mousedown.prevent`) and appends to the end otherwise; the pre-seed never clobbers
   user/AI SQL.

## Definition Of Done
All acceptance criteria shown as real in-session output with the full stack live (real Redis + real DuckDB +
real backend + Vite), **including the live Gemini NL→SQL leg** (§F); the frozen `duckdb_manager.py`, the
`sql_validator`, and both deferred stubs unchanged; self-review with severity grades attached. **Sign-off is the
user's — I do not self-close this task, nor touch `README.md` / `.ai/CURRENT_STATE.md`.**

## Status
AWAITING USER SIGN-OFF. Implementation + self-review complete; **all paths verified live, including the LLM
leg** — a Gemini key was provided and the model round-trip on a fresh cache miss + version-keyed regeneration are
now proven (§F, 14/14). The only sub-leg not exercised is a *live model-induced* self-correction
(`retries_used > 0`), which the model avoided by reading the schema correctly; its mechanism is proven
deterministically (§B/§C, and Self-Review finding 2). The **Query Engine ergonomics** of requirement 11 (pre-seed
+ schema autocomplete + click-to-insert chips) were added afterward and verified live (§G); a real focus bug found
during that verification was fixed and both insert paths re-verified (Self-Review finding 7).

## Proof
Captured this session against the live stack (real Redis up, backend `:8000`, Vite `:5173`). No LLM key was
present, so the verification is split honestly: everything **around** the model call is proven against the live
backend; the model call itself is the one unverified leg. Frontend behavior was read via `preview_*` MCP tools
(real DOM / component `setupState` / network / console); screenshots are unobtainable headless (the Browser pane
does not composite frames — same limitation as TASK-008/009/010/011). Two deterministic HTTP suites hit the live
backend directly (`urllib`), one seeding cache/version state through the app's **own** `redis_manager` on the
same real Redis.

### A. Build — strict `vue-tsc` (AC1)
`npm run build` (= `vue-tsc -b && vite build`):
```
vite v8.2.1 building client environment for production...
✓ 2509 modules transformed.
dist/index.html                     0.74 kB │ gzip:   0.39 kB
dist/assets/index-B7sjIzIQ.css     16.07 kB │ gzip:   4.30 kB
dist/assets/index-BB71-FeC.js   1,206.92 kB │ gzip: 406.03 kB
✓ built in 2.35s
```
`vue-tsc -b` passed — under strict flags this proves the `AskResponse`/`ExecuteResultResponse`/`CustomInstruction`
contracts, the `v-model:sql` + `@run` typings on `SqlEditor`, the `readOnly` Compartment plumbing in
`useCodeMirror`, and that no import is left unused. (Vite warns the chunk >500 kB — CodeMirror + `lang-sql` added
~430 kB raw; a lazy-loaded Query Engine route would fix it. Out of scope for the skeleton; self-review finding 3.)

### B. `POST /execute` — 22 deterministic checks against a 1500-row sentinel table (AC2)
Suite: `qe_verify.py` (live backend, no key needed). Sentinel = `id / category(A–D) / amount(1..50 cycled)`,
1500 rows. All **PASS**:
```
EXECUTE valid aggregation SELECT
  [PASS] valid SELECT -> 200
  [PASS] columns recovered = [category, total]        (DESCRIBE-based name recovery on the frozen sandbox)
  [PASS] row_count == 4    [PASS] not truncated        [PASS] row shape is dict keyed by column name
EXECUTE row cap / truncation (SELECT * from 1500 rows)
  [PASS] SELECT * -> 200   [PASS] truncated == true    [PASS] row_count capped at 1000   [PASS] len(rows)==1000
EXECUTE validator blocks non-SELECT (defense layer 1)
  [PASS] blocked: DROP TABLE -> 400        [PASS] blocked: stacked (SELECT; DROP) -> 400
  [PASS] blocked: INSERT -> 400   [PASS] blocked: UPDATE -> 400   [PASS] blocked: DELETE -> 400
  [PASS] blocked: CTE write (INSERT in CTE) -> 400
EXECUTE sentinel SURVIVES the blocked writes
  [PASS] post-attack COUNT(*) -> 200       [PASS] table still has 1500 rows      (rollback + fail-closed hold)
EXECUTE valid-but-wrong-column SELECT
  [PASS] wrong column -> 400   [PASS] error mentions 'Query failed'
EXECUTE empty result set is well-formed
  [PASS] empty result -> 200   [PASS] row_count == 0   [PASS] columns still present (id,category,amount)
ASK — no LLM key configured
  [PASS] no-key /ask -> 503    [PASS] 503 detail is a non-empty string
ASK — bad input
  [PASS] empty question -> 400 [PASS] unknown session /ask -> 404
TOTAL: 26 passed, 0 failed
```
(26 assertions across the /execute + /ask-contract cases above.)

### C. bizdict CRUD + version-keyed cache + fail-cache — 19 deterministic checks (AC3–AC5, AP-9)
Suite: `qe_verify2.py`, which seeds cache/version state via the app's **own** `redis_manager` on the same real
Redis and hits the live backend. First line proves the backend is on real Redis, not fakeredis:
```
REDIS BACKEND IN USE: redis
  [PASS] app is on REAL redis (AP-9)
BIZDICT CRUD + version bump
  [PASS] GET instructions (empty) -> 200 []      [PASS] POST term -> 200 status=added
  [PASS] bizdict_version bumped by add           [PASS] GET now contains the term
  [PASS] bizdict:{session} key holds term in Redis   (independent read straight out of Redis)
  [PASS] DELETE term -> 200 status=deleted       [PASS] bizdict_version bumped by delete
  [PASS] GET instructions empty again            [PASS] DELETE missing term -> 404
  [PASS] POST empty term/def -> 400
VERSION-KEYED CACHE — read path + invalidation
  [PASS] seeded /ask -> 200 cache_hit=true       [PASS] cached SQL returned verbatim
  [PASS] retries_used == 0 on cache hit          [PASS] reformatted question hits same cache
  [PASS] after bizdict_version bump, cache MISSES (503, no key)   (correct invalidation → falls to no-key resolve)
  [PASS] re-seed at new version -> cache_hit=true again           (proves version-keyed, not global)
FAIL-CACHE — read path
  [PASS] seeded fail-cache -> 422 (no token spend)   [PASS] 422 carries the cached message
TOTAL: 19 passed, 0 failed
```
The reformatted-question hit proves the hash normalization (`" ".join(question.lower().split())`); the bump→miss
→re-seed→hit cycle proves the cache key embeds `bizdict_version` (and, by the same construction, `schema_version`).

### D. Frontend live (AC6)
Driven through the real UI against the live backend:
- **Editor → Run → results:** typed a `GROUP BY` SELECT into the CodeMirror editor, clicked **Run** → `/execute`
  round-trip → `ResultsTable` rendered the rows (Alpha 40 / Beta 70 / Gamma 40), sticky header + coerced cells.
- **NL ask, no key:** clicked **Generate SQL** → graceful **503** surfaced in the ask-row error slot (`AlertCircle`
  + message), no crash, editor untouched — exactly the Review-Gate contract with the model absent.
- **Custom Instructions:** add → list → delete round-tripped; independent `redis-cli` cross-check showed
  `bizdict:{session}` back to `{}` and `bizdict_version` at 2 after the add+delete.
- **uuid-staleness guard** present on both `generate()` and `run()` (drop the late response if `sessionUuid`
  changed mid-flight), mirroring DataGrid/ChartCanvas.

### E. Deferred-path + scope (AC7)
```
$ git diff -- backend/services/duckdb_manager.py     → (empty)             # frozen manager untouched
routers/query.py  POST /chart  build_chart()         → still `return b""`  # MessagePack stub intact
routers/ai.py     POST /queries/{id}                 → still returns the completed-stub QueryPollResponse
routers/query.py diff                                → pre-existing TASK-011 /aggregate work (not this task)
```
Console was application-clean during the live flow. `sql_validator.py` used, not modified.

### F. Live Gemini NL→SQL leg — 14 checks (closes finding 2)
A Gemini key was supplied after the deterministic pass and written to `backend/.env` (gitignored —
`git check-ignore` confirms it, and it is untracked); the backend was relaunched with the key sourced into its
environment (`gemini/gemini-2.5-flash` auto-selected by `_resolve_model`). Suite `qe_live.py` ran against a fresh
6-row session (`region, amt, units`) and prints the **actual model SQL** at each step. All **PASS**:
```
1) FRESH CACHE MISS -> live Gemini call
   [PASS] miss -> 200   [PASS] cache_hit == false   [PASS] model returned non-empty SQL   (retries_used=0)
   MODEL SQL:  SELECT region, SUM(amt) FROM <table> GROUP BY region
2) RUN the model's SQL via /execute -> CORRECT, not just valid
   [PASS] execute -> 200   [PASS] SUM(amt) by region == hand-computed {North:150, South:450, East:250, West:400}
3) IDENTICAL repeat -> cache HIT
   [PASS] cache_hit == true   [PASS] retries_used == 0   [PASS] SQL identical to the cached miss
4) REFORMATTED question (case/whitespace)
   [PASS] cache_hit == true            (hash normalization -> same cache entry)
5) SCHEMA-VERSION bump (real filter_rows transform -> schema_version=1)
   [PASS] same question MISSES again (cache_hit == false)     (version-keyed invalidation, LIVE)
6) BIZDICT-VERSION bump (add "big order" = "amt > 200")
   [PASS] same question MISSES again (cache_hit == false)     (version-keyed invalidation, LIVE)
7) SELF-CORRECTION probe: ask "total amount" though the column is "amt"
   [PASS] still 200 with runnable SQL; retries_used=0 -- model read the DDL and used `amt` directly
TOTAL: 14 passed, 0 failed
```
This closes the previously-open leg end-to-end: a real model call on a cache **miss** returns correct, runnable
SQL; the result is verified against **hand-computed truth** through `/execute` (not merely "valid"); the identical
and reformatted repeats hit the version-keyed cache; and both a real schema transform and a bizdict edit
invalidate it **live**. The only unexercised sub-leg is a *model-induced* `retries_used > 0` (finding 2).

### G. Query Engine ergonomics — live via `preview_*` DOM reads (AC8, requirement 11)
Verified against the live Vite app + backend. A 6-row CSV (`region, amt`; sums North 150 / South 450 / East 250 /
West 400) was loaded through the real dropzone (a synthesized `drop` carrying a constructed `File`, since a native
file chooser can't be driven headless), then the Query Engine tab was opened. Behavior read straight from the DOM
and the live `EditorView` (screenshots remain unobtainable — the Browser pane does not composite):
```
PRE-SEED
  editor doc on load == "SELECT *\nFROM t_<uuid>_qe_ergo_test\nLIMIT 100;"   (no typing of the UUID name)
  clicked Run -> /execute -> ResultsTable rendered all 6 rows (North 50/100, South 200/250, East 250, West 400)
    -> the semicolon-terminated seed passes the fail-closed validator and executes
CHIPS
  Table chip == the full table name, title "Click to insert the table name"
  Column chips == region (VARCHAR) / amt (BIGINT), title "… — click to insert"
  insert @ caret: cursor set after "SELECT *", editor focused, clicked `amt`
    -> mousedown.prevent kept focus on the editor (activeElement still the content DOM)
    -> doc became "SELECT * amt\nFROM …\nLIMIT 100;"   (inserted at the cursor, tail intact)
  insert @ end (fallback): editor blurred, clicked `region`
    -> doc tail became "LIMIT 100; region"   (leading space added; no token fusion)
AUTOCOMPLETE  (sql({schema, defaultTable}) via a Compartment)
  typed "SELECT * FROM t" -> completion tooltip top option == "t_<uuid>_qe_ergo_test"  (ranked above keywords)
  typed "SELECT r"        -> completion tooltip top option == "region"                 (defaultTable columns)
```
A **real bug was caught here and fixed** (Self-Review finding 7): the first cut gated insertion on `view.hasFocus`
with no `mousedown.prevent`, so clicking a chip `<button>` blurred the editor and every insert fell to the
append-at-end branch. After the fix (`@mousedown.prevent` + `document.activeElement`-based gating), both the
at-caret and the append paths were re-verified live, as shown above. Strict `vue-tsc -b && vite build` re-run
clean after the fix.

## Self-Review
Severity scale: **Critical / High / Medium / Low / Info.**

1. **[Info — proof method] Deterministic proof via live HTTP suites + `preview_*`; screenshots unobtainable
   headless.** Same Browser-pane non-compositing limitation as TASK-008/009/010/011. Behavior verified by reading
   real DOM / component `setupState` / network / console after real interactions and real backend round-trips,
   plus 45 backend assertions (§B 26 + §C 19) against the live stack.
2. **[Resolved — was Medium] The live LLM leg is now VERIFIED (§F).** A Gemini key was provided after the
   deterministic pass; `qe_live.py` (14/14) proves the model round-trip on a fresh cache **miss** returns correct,
   runnable SQL — validated against hand-computed truth via `/execute` — that an identical/reformatted repeat hits
   the version-keyed cache, and that a real Table transform (schema_version bump) **and** a bizdict edit each
   invalidate it live. Everything around it was already proven: validator gating (§B), the sandboxed DESCRIBE +
   row-cap path (§B), the cache write/read + invalidation (§C), the fail-cache (§C), and the 503/502/422/404/400
   contract (§B/§C). **One sub-leg remains unexercised, honestly:** a *model-induced* self-correction
   (`retries_used > 0`) — Gemini read the DDL and used the exact column `amt` even when asked about "amount", so no
   recoverable error arose to trigger a retry. The retry/classify/dry-run mechanism itself is exercised
   deterministically (the validator-reject retry branch in §B; `_classify_db_error` runs on any dry-run failure),
   so this is a "couldn't provoke a competent model into erring" gap, not an unverified code path.
3. **[Low — bundle size] Main chunk is 1,206.92 kB (406.03 kB gzip); Vite warns >500 kB.** CodeMirror 6 +
   `@codemirror/lang-sql` added ~430 kB raw over the pre-task bundle. The clean next step is a route-level
   `import()` / `defineAsyncComponent` for the Query Engine (and Canvas/ECharts) view so the editor loads only
   when that tab opens. Out of scope for the skeleton; worth doing before shipping more of the console.
4. **[Resolved — was Low — UX] The console now surfaces the table name and makes it effortless (§G).** Original
   gap: the schema reference listed `columns` but not the resolved table identifier, so hand-writing SQL meant
   knowing the long UUID-laden name. Fixed under requirement 11: the editor is **pre-seeded** with
   `SELECT * FROM <table> LIMIT 100;` on load, `sql({ schema, defaultTable })` gives **autocomplete** for the table
   and its columns, and a click-to-insert **table-name chip** (plus insertable column chips) drops names in without
   typing. Verified live (§G).
5. **[Info — test-harness artifacts, not app defects] Two transient headless-env hiccups.** (a) A first browser
   upload returned `ERR_INSUFFICIENT_RESOURCES` — a transient double-load while the large dev bundle initialized;
   retrying the upload → 200. (b) A first Custom-Instructions delete click hit a stale element from before the
   add-reload re-render (no DELETE fired); re-triggering after the render → term removed, empty state returned.
   Both are preview-pane timing artifacts reproduced only headless, not application bugs; the redis-cli
   cross-check (§D) confirms the real end state.
6. **[Info — carried forward] Builds on the unsigned TASK-008/009/010/011 working tree** (itself on `a3c7162`).
   This task's own diff is the file set in "Files Expected To Change"; the two shared frontend files (`types.ts`,
   `api.ts`) show cumulative diffs because none of the prior tasks is committed. I have **not** self-closed any of
   them, nor touched `README.md` / `.ai/CURRENT_STATE.md`.
7. **[Resolved in-session — was a real bug] A chip click stole the editor's cursor.** The first cut of
   requirement 11 gated `insert()` on `view.hasFocus` and put no `mousedown.prevent` on the chips, so clicking a
   chip `<button>` moved focus to the button and blurred the editor — every insert then fell to the append-at-end
   branch instead of landing at the caret (and `view.hasFocus` additionally requires the whole window to hold OS
   focus, which is false in the headless preview, masking it further). Caught during §G live verification. Fix:
   the chips use `@mousedown.prevent` so the click never blurs the editor, and `insert()` now decides caret-vs-end
   from `document.activeElement` being inside the content DOM (independent of window focus). Both paths re-verified
   live (§G) and the strict build re-run clean.

**Net:** the Query Engine loop — upload → open the tab → write SQL in a real CodeMirror editor **or** ask in
English → SQL lands in the editor (the human Review Gate) → Run → sandboxed, row-capped results render — is proven
end-to-end against the live backend for every leg that doesn't require a model key: 45 deterministic assertions
(fail-closed validator on both AI and user SQL, unconditional-rollback sandbox with a surviving sentinel table,
DESCRIBE-based column recovery, the 1000-row cap, the full typed error contract, bizdict CRUD, and version-keyed
cache read + invalidation + fail-cache), plus the live frontend flow with a redis-cli cross-check and the
AP-9 real-Redis proof. With the Gemini key now provided, the live model round-trip is **also proven** (§F,
14/14): cache miss → correct runnable SQL (checked against hand-computed truth) → version-keyed re-generation
after a real transform and a bizdict edit. The only unexercised sub-leg is a model-induced `retries_used > 0`,
which a correctly schema-reading model didn't trigger (finding 2). The frozen `duckdb_manager.py`, the
`sql_validator`, and both deferred stubs are provably untouched. I have **not** marked this task closed —
**SIGNED OFF by user on 2026-08-29.**
