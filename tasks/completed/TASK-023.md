# TASK-023 — Wave 4: AI batch (the intelligence layer across all three pillars)

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
Wave 4 adds six LLM-backed helpers that make Spencer *explain itself* — spread across the three
pillars but sharing one substrate (LiteLLM → Claude **or** Gemini by env key) and one non-negotiable
rule: **the model never runs anything.** Every SQL the model emits returns to the human Review Gate;
every narrative is read-only prose built from data the client already holds.

| # | Feature | Pillar | Endpoint | Shape |
|---|---------|--------|----------|-------|
| **#26** | Auto-EDA — suggested questions on upload | Table | `GET /{uuid}/suggest-questions` | cached `eda:{uuid}:{sv}` |
| **#21** | Conversational refinement (follow-up turns) | Query | `POST /{uuid}/ask` (+`history`) | folds into `query:` cache hash |
| **#22** | Explain / optimize / fix SQL | Query | `POST /{uuid}/sql/assist` | uncached; fix/optimize re-validated |
| **#29** | Data storytelling — dataset narrative | Canvas | `GET /{uuid}/narrate` | cached `story:{uuid}:{sv}` |
| **#30** | Chart-type recommendation | Canvas | `POST /{uuid}/recommend-chart` | uncached; column is prompt context only |
| **#18** | Explain this chart (per-series narrative) | Canvas | `POST /{uuid}/explain-chart` | uncached; keys/values are prompt context only |

## The one invariant this wave had to respect: the model proposes, the human disposes
Two of the six emit SQL (#21 via `/ask`, #22-fix/optimize via `/sql/assist`). Both route through the
**same three-layer defense** the AI-SQL path already ships, and neither executes:
1. **`sql_validator.validate()`** — fail-closed allowlist (SELECT-only, no DDL/DML, single statement).
2. **`db_manager.run_sandboxed()`** — unconditional-rollback dry-run proves the SQL is executable without
   touching the live table.
3. **Human Review Gate** — the validated SQL is *returned to the editor*, never auto-run. The user reads
   it and presses Run themselves (QueryConsole is the client-side gate).

The other four (#26, #29, #30, #18) emit **no SQL at all** — they are prose/enum responses built from the
schema or from an aggregate the client already computed. `#30`'s column name and `#18`'s keys/values are
**prompt context only**; no query is assembled from them.

## What changed
### Backend
- **`backend/routers/ai.py`** — five new endpoints + the `/ask` extension:
  - **`/ask` (#21):** optional `history: [{question, sql}]`. `_ask_cache_hash(question, history)` is
    **byte-identical to the pre-#21 `_question_hash(question)` when history is empty** (so every existing
    cache entry still hits); with history, prior turns fold into the hash so a follow-up ("now top 3")
    can't collide with the base question's cached SQL. History is passed to `ai_service.resolve_sql`.
  - **`/sql/assist` (#22):** `mode ∈ {explain, fix, optimize}`. `explain` → prose only (`sql=None`).
    `fix`/`optimize` → a **new** SELECT that is re-validated + dry-run exactly like `/ask` before return
    (the submitted SQL is untrusted). `error` (optional) is forwarded so `fix` can target the DB message.
  - **`/suggest-questions` (#26):** schema → ~5 analytical questions, each ready to drop into `/ask`.
    Cached `eda:{uuid}:{sv}` — a transform regenerates (version bump), a revisit is free (`cache_hit`).
  - **`/narrate` (#29):** schema → plain-prose dataset overview. Cached `story:{uuid}:{sv}`.
  - **`/recommend-chart` (#30):** `{column, column_type?, intent?}` → `{chart_type, reasoning, alternatives}`,
    `chart_type` constrained to the Canvas-supported set.
  - **`/explain-chart` (#18):** `{title, chart_type, dimension, measure, aggregation, keys, values}` →
    narrative. **No query runs** — the aggregate is supplied by the client.
  - **Uniform error mapping** (`_llm_http`): `LLMConfigError → 503` (fix the env), `LLMAPIError → 502`
    (provider/transport, retry), resolve/base `→ 422` (reword). Empty input `→ 400`, no schema `→ 404`.
- **`backend/services/ai_service.py`** — new prompt/parse functions: `explain_sql`, `rewrite_sql`
  (fix/optimize, with the validate+dry-run retry loop, `MAX_ATTEMPTS=3`), `suggest_questions`,
  `narrate_dataset`, `recommend_chart`, `explain_chart`; `resolve_sql` gains a `history` arg.
- **`backend/models/schemas.py`** — `AskRequest.history`, `AskTurn`, `SqlAssistRequest`/`SqlAssistResponse`,
  `SuggestQuestionsResponse`, `NarrativeResponse`, `RecommendChartRequest`/`RecommendChartResponse`,
  `ExplainChartRequest` (all additive).

### Frontend
- **`frontend/src/services/api.ts`** — `askQuestion(uuid, q, history?)`, `sqlAssist(uuid, mode, sql, error?)`,
  `suggestQuestions`, `narrateDataset`, `recommendChart`, `explainChart`. History/optional args are omitted
  when empty so the default `/ask` request is unchanged.
- **`frontend/src/types.ts`** — `AskTurn`, `SqlAssistMode`/`SqlAssistResponse`, `SuggestQuestionsResponse`,
  `NarrativeResponse`, `RecommendChartResponse`, `ExplainChartRequest`.
- **`frontend/src/composables/useQuestionHandoff.ts`** (new) — module-singleton (`reactive` + read-and-clear
  `takePendingQuestion()`) that carries a clicked suggestion from Table → Query Engine across the router.
- **`frontend/src/components/SuggestedQuestions.vue`** (new, #26) — auto-loads on `sessionUuid`/`dataVersion`,
  session-switch-safe (drops stale responses), Refresh, click → `askInQueryEngine(q)` + `router.push('/query')`.
  Mounted in **`TableView.vue`** between the upload bar and the data-quality panel (`v-if="sessionUuid"`).
- **`frontend/src/components/QueryConsole.vue`** (new home of the editor; #21 + #22) — `generate()` threads
  the running `turns` history (cap `MAX_TURNS=6`); a **"building on N question(s)"** chip + **"Start fresh"**
  reset the thread; `consumePending()` (on `onActivated`, keep-alive) seeds the box from the handoff. **Explain**
  / **Optimize** buttons and a **"Fix with AI"** action on the run-error banner call `assist(mode)`, which
  renders a dismissible assist panel (self-corrected count when retries>0); fix/optimize drop their returned
  SQL back into the editor (never auto-run).
- **`frontend/src/components/ResultsTable.vue`** (new) — the Query Engine result grid (extracted so the
  console/results split is clean; ECharts-free).
- **`frontend/src/components/ChartCanvas.vue`** (#29) — **"Tell the story"** button → `narrateDataset`;
  dismissible narrative panel; cleared on session switch and on `dataVersion` bump (schema change ⇒ stale).
- **`frontend/src/components/ChartTile.vue`** (#18 + #30) — per-tile **Recommend** (Lightbulb) and **Explain**
  (Sparkles) buttons. Recommend renders reasoning + **clickable alternative chips** (each `applyType`) and
  **auto-applies the primary recommendation** (guarded no-op if already that type). Explain renders the
  per-series narrative. Both dismissible; both uuid-staleness-guarded.

### Test
- Backend AI endpoints were exercised **live end-to-end** (real Gemini + real Redis) rather than mocked —
  see Verification. (No new committed `test_*.py` this wave; the AI path is non-deterministic prose/enum and
  is proven by live round-trip + the shared validate/dry-run tests that already cover the SQL-emitting path.)

## Files that MUST NOT change (verified untouched)
`README.md`, `.ai/CURRENT_STATE.md`, `backend/services/duckdb_manager.py`, `backend/sql_validator.py` —
confirmed absent from my diff. `.ai/CURRENT_STATE.md` **does** show a diff, but it is the **parallel
TASK-013 work pre-existing at session start — not mine** (I edited none of it; likewise `session.py`).

## Security (AP-8)
- **The model never executes (ADR — Review Gate).** `#21`/`#22-fix/optimize` return SQL to the editor after
  the **same** `sql_validator.validate()` + `run_sandboxed()` dry-run the `/ask` path uses; the user runs it.
  `#26`/`#29`/`#30`/`#18` emit no SQL — prose/enum only.
- **Untrusted-in, validated-out.** `#22`'s submitted SQL is treated as untrusted: fix/optimize output is
  re-validated + dry-run before it is ever shown, so a model that "fixes" one error into an unsafe statement
  is caught by the allowlist, not the database.
- **No SQL built from free text.** `#30`'s `column` and `#18`'s `keys/values/dimension/measure` are **prompt
  context only** — they are never interpolated into a query. `#18` runs **zero** queries (the client supplies
  the aggregate it already rendered).
- **Fail-closed, uniform mapping.** Empty question/SQL/column `→ 400`; missing schema `→ 404`; not-configured
  `→ 503`; provider/transport `→ 502`; model-couldn't-produce `→ 422`. No path 500s on a bad-but-expected input.
- **Bounded token burn.** `#26`/`#29` are cached per `schema_version` (repeat = free, `cache_hit=true`);
  `/ask` failures are briefly fail-cached so a repeated bad question doesn't re-spend. `#18`'s payload rides
  the **existing server-side top-N category cap** on the aggregate (ChartTile already truncates), so a
  high-cardinality dimension can't balloon the prompt.
- **Secrets untouched.** The real `GEMINI_API_KEY` lives only in gitignored `backend/.env`; no key is read,
  logged, or returned by any endpoint. Provider selection is by env presence, resolved in `ai_service`.
- **Single-table (ADR-006), single-writer (unchanged).** No new write path; the AI layer is read-or-propose only.

## Acceptance criteria (all proven live)
1. ✅ Strict `vue-tsc -b && vite build` clean (the >500 kB line is the known pre-existing ECharts-in-Canvas
   advisory; router uses static imports → single bundle by design). No **new** ECharts coupling on the
   Table/Query paths — only `ChartTile` (Canvas) imports echarts; SuggestedQuestions/QueryConsole/ResultsTable are clean.
2. ✅ **#26 render + handoff:** on `/table`, "Suggested questions" shows 5 real questions; clicking one routes
   to `/query`, seeds the box, and generates
   `SELECT region, SUM(amount) AS total_sales_amount … GROUP BY region`.
3. ✅ **#21 refinement:** after the handoff the Query console shows the **"building on 1 question"** chip +
   **"Start fresh"**; backend proof — turn 2 "top 3" appended `ORDER BY SUM(amount) DESC LIMIT 3` onto turn 1's
   SQL; an empty-history `/ask` hash is byte-identical to pre-#21 (existing cache still hits).
4. ✅ **#22 explain/optimize/fix:** Explain rendered "What this query does" prose (`sql=null`) live; Optimize
   returned a validated SELECT; Fix repaired `regio`→`region`. All three buttons render (Explain/Optimize by
   Save/Run; "Fix with AI" on the run-error banner).
5. ✅ **#29 storytelling:** "Tell the story" rendered a dataset overview live ("…detailed records of individual
   sales orders … a potential caveat is that the table name suggests a sample dataset"); `story:{uuid}:0` in Redis.
6. ✅ **#30 recommend:** rendered **"Bar — ideal for comparing a quantitative value across discrete
   categories"** + **"Try instead: Horizontal bar, Pie"**; clicking the **Pie** chip switched the tile's Type
   dropdown to `pie` (`applyType` round-trip proven). Primary recommendation auto-applies (guarded no-op when unchanged).
7. ✅ **#18 explain chart:** rendered a real per-series narrative with actual values ("West recorded the
   highest sum with 10220, closely followed by East at 10210 … remarkably similar across regions").
8. ✅ **Cache backend genuine:** `eda:{uuid}:0` and `story:{uuid}:0` written to **real** redis-server v5.0.14.1
   on :6380 (DB0 `dbsize`/`KEYS` confirmed); `#26` repeat returned `cache_hit=true`. fakeredis is in-process and
   could not populate the live server.
9. ✅ **Error mapping:** not-configured/provider/model-failure map to 503/502/422; empty input → 400; no data → 404.
10. ✅ Must-not-change diffs empty for `README.md`, `.ai/CURRENT_STATE.md` (mine), `duckdb_manager.py`, `sql_validator.py`.

## Verification (real output)
- **Live full stack** — Redis (:6380), backend `uvicorn --workers 1` (:8000), Vite (:5173), against
  `sample_sales.csv` (40 rows; order_id/region/category/rep/amount/quantity/order_date).
- **Backend, real Gemini:** all six endpoints returned real content (see the AC results above); `#26`/`#29`
  cache keys observed in the live Redis DB0.
- **Browser render proof** (accessibility snapshots + DOM reads, pane not composited so screenshots skipped):
  #26 panel on `/table`; handoff → `/query` with generated SQL; #21 chip + Start fresh; #22 Explain panel with
  real prose; #29 narrative; #30 reasoning + alternatives + a proven Bar→Pie chip apply; #18 per-series narrative.
- Strict frontend build clean.

## Definition of Done
Six AI helpers implemented across all three pillars over one LiteLLM substrate and the existing three-layer
SQL defense, self-reviewed with severity grades (below), all ACs proven live (browser + backend). Left in
`tasks/active/` for the user's single wave sign-off. Not self-closed. `README.md` / `.ai/CURRENT_STATE.md` untouched.

## Self-review (severity-graded)
**Critical / High: none.**

- **S-1 (Medium — by design, flagged for your call).** *#30 auto-applies the primary recommendation.* Clicking
  **Recommend** immediately switches the tile to the recommended chart type (guarded to a no-op if it already
  matches — which is why our live "Bar→Bar" run showed no visible change), *and* renders the alternatives as
  clickable chips. Rationale: a user pressing "recommend a chart type" is asking to be *given* one, and it's
  instantly reversible (an alternative chip, the Type dropdown, or Undo). But it **does mutate their view on a
  read-flavoured action**, which can surprise. If you'd prefer "suggest but don't apply" (render the pick +
  chips, apply only on click), that's a one-line change (drop the `applyType(res.chart_type)` at
  `ChartTile.vue:338`). Say the word.
- **S-2 (Low — by design).** *AI panels can go stale after you change the chart/config.* `#18`'s narrative and
  `#30`'s recommendation describe the tile **at the moment you asked**; if you then change dimension/measure the
  panel text stays until you dismiss it or re-run. Each call is uuid-staleness-guarded (a session switch drops an
  in-flight response), but there is no config-change auto-invalidate — deliberate, so a panel you're reading
  doesn't vanish under you. `#29`'s story **is** cleared on a `dataVersion` bump (schema change ⇒ regenerate).
- **S-3 (Low — by design).** *#21 refinement is capped at `MAX_TURNS=6`.* Beyond six turns the oldest context
  drops from the folded history (the chip still counts the live thread). Keeps the prompt bounded; "Start fresh"
  resets deliberately. A longer window is a tuning change, not a redesign.
- **S-4 (Low — by design).** *`#26`/`#29` cache is keyed on `schema_version` only, not row content.* A transform
  that changes rows but not the schema (e.g. a row filter) still bumps `schema_version` (every transform does),
  so in practice the narrative/questions regenerate; but they are **schema-derived** (qualitative) by design, so
  they wouldn't change on pure row deltas anyway. `#18` always reflects current data (the client passes live
  keys/values, uncached).
- **S-5 (Low).** *No committed unit test for the AI endpoints this wave.* The responses are non-deterministic
  prose/enum, so they're proven by **live** end-to-end round-trip (above) rather than asserted strings; the
  deterministic, security-critical part — validate + dry-run on the SQL-emitting path — is already covered by
  the shared `/ask` tests that `#22`-fix/optimize reuse verbatim. A structural test (mode routing, error mapping,
  cache-hit flag) could be added if you want it committed.
- **S-6 (Info).** *Provider is whichever key is present in `backend/.env`.* All live proof this wave ran on
  **Gemini**; the Claude path shares the identical `litellm.acompletion` call and validation, but was not
  re-exercised here. Swapping keys switches providers with no code change.
- **S-7 (Info).** *One live test-upload session remains in `spencer.db`* (and its `eda:`/`story:` keys in Redis);
  both expire via the normal session TTL sweeper. No manual cleanup needed.
