"""Query Engine routes (Phase 6): NL->SQL, SQL execution, and the business
dictionary. Mounted under /sessions (see main.py), so paths are
/sessions/{session_uuid}/...

The three-layer AI-SQL defense (ARCHITECTURE.md / ADR-010, ADR-013) lives here:
  1. sql_validator.validate() -- fail-closed; gates BOTH the model's output
     (inside ai_service) AND any SQL the user submits to /execute (they may have
     edited it in the editor). A non-SELECT / multi-statement / write is rejected.
  2. db_manager.run_sandboxed() -- every execution runs in a transaction that is
     ALWAYS rolled back, so nothing here can mutate a session's data.
  3. the human Review Gate (frontend) -- generated SQL is shown in the editor and
     only runs when the user clicks Run. This router never auto-executes /ask output.

run_sandboxed returns rows WITHOUT column names (and duckdb_manager is frozen), so
/execute recovers names with a read-only `DESCRIBE SELECT * FROM (<sql>) _q` on the
same sandboxed path and caps rows with a `LIMIT N+1` wrap + a `truncated` flag.
"""

import hashlib
import logging
from typing import List

from fastapi import APIRouter, HTTPException

from models.schemas import (
    AskRequest, AskResponse,
    ExecuteRequest, ExecuteResultResponse,
    QueryPollResponse,
    CustomInstruction,
    PreviewColumn,
    SqlAssistRequest, SqlAssistResponse,
    SuggestQuestionsResponse,
    NarrativeResponse,
    RecommendChartRequest, RecommendChartResponse,
    ExplainChartRequest,
)
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager
from services.sql_validator import sql_validator
from services.ai_service import (
    ai_service,
    LLMError,
    LLMConfigError,
    LLMAPIError,
    LLMRateLimitError,
    LLMResolveError,
)

logger = logging.getLogger("spencer.ai")

router = APIRouter()

# One-shot result cap for /execute. Mirrors query.py's MAX_LIMIT: a single query
# result can't pull an unbounded set into memory or into the in-memory results
# table. We fetch one extra row to detect truncation, then trim.
MAX_ROWS = 1000


def _question_hash(question: str) -> str:
    """SHA-256 of the lowercased, whitespace-normalized question (DATABASE.md).
    "  SELECT top  Users " and "select top users" hash identically, so trivial
    reformatting still hits the cache."""
    normalized = " ".join(question.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ask_cache_hash(question: str, history: list) -> str:
    """Cache key input for /ask. With NO history this is byte-identical to
    _question_hash(question), so pre-#21 cache entries still hit. With history, the
    prior turns fold into the hash so a follow-up ("now group by month") never
    collides with the base question's cached SQL."""
    if not history:
        return _question_hash(question)
    parts = [question] + [f"{t.question}|{t.sql}" for t in history]
    return _question_hash(" ".join(parts))


def _llm_http(exc: LLMError) -> HTTPException:
    """Map an AI-path error to the uniform HTTP status the frontend expects:
    503 not-configured (fix the env), 502 provider/transport (retry), 422 the
    model couldn't produce a usable result (reword / try again)."""
    if isinstance(exc, LLMConfigError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, LLMRateLimitError):
        # Every pooled key is spent (TASK-024). Retryable -- tell the client how long to
        # wait. Checked before LLMAPIError because it is a subclass of it.
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        return HTTPException(status_code=429, detail=exc.message, headers=headers)
    if isinstance(exc, LLMAPIError):
        return HTTPException(status_code=502, detail=exc.message)
    return HTTPException(status_code=422, detail=exc.message)  # LLMResolveError / base


@router.post("/{session_uuid}/ask", response_model=AskResponse)
async def ask_question(session_uuid: str, payload: AskRequest):
    """NL question -> a validated, dry-run-clean SQL SELECT (the Review Gate: the
    SQL is returned for the user to inspect/run, never executed here).

    Cache is version-keyed (query:{qh}:{schema_version}:{bizdict_version}): a
    transform bumps schema_version and a bizdict edit bumps bizdict_version, so
    stale SQL is simply never read again -- no explicit invalidation. Failures are
    cached briefly (fail:...) to bound token burn on a repeated bad question.

    #21: an optional `history` of prior (question, sql) turns lets a follow-up
    refine the last query; it folds into the cache hash so refinements don't
    collide with the base question."""
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")

    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")
    bizdict = redis_manager.get_json(f"bizdict:{session_uuid}") or {}

    history = payload.history or []
    hist = [{"question": t.question, "sql": t.sql} for t in history]
    qh = _ask_cache_hash(question, history)
    sv = redis_manager.get_version(session_uuid)
    bv = redis_manager.get_bizdict_version(session_uuid)

    cached_sql = redis_manager.get_sql_cache(qh, sv, bv)
    if cached_sql is not None:
        return AskResponse(sql=cached_sql, cache_hit=True, retries_used=0)

    cached_fail = redis_manager.get_fail_cache(qh, sv, bv)
    if cached_fail is not None:
        # Same failure we already surfaced for this question+versions -- no re-spend.
        raise HTTPException(status_code=422, detail=cached_fail.get("message", "Could not generate SQL."))

    try:
        result = await ai_service.resolve_sql(question, schema, bizdict, history=hist)
    except LLMConfigError as exc:
        # Backend not configured (no key / litellm missing). Not the user's fault
        # and not cacheable -- fixing the env should work immediately.
        logger.warning("ask: LLM not configured: %s", exc.message)
        raise HTTPException(status_code=503, detail=exc.message)
    except LLMRateLimitError as exc:
        # All pooled keys are rate-limited / quota-exhausted (TASK-024). Transient, so
        # surface a 429 (+Retry-After) and do NOT fail-cache it (a freed key must be
        # tried next time). Caught before LLMAPIError -- it is a subclass.
        logger.warning("ask: all keys rate-limited: %s", exc.message)
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        raise HTTPException(status_code=429, detail=exc.message, headers=headers)
    except LLMAPIError as exc:
        # Transient provider/transport failure. Retryable, and NOT cached as a
        # permanent failure (a network blip must not poison the question).
        logger.warning("ask: LLM API error: %s", exc.message)
        raise HTTPException(status_code=502, detail=exc.message)
    except LLMResolveError as exc:
        # Bounded self-correction exhausted without valid SQL. Cache the failure
        # (short TTL) so an identical retry doesn't burn tokens again.
        redis_manager.set_fail_cache(qh, sv, bv, exc.as_error())
        raise HTTPException(status_code=422, detail=exc.message)

    redis_manager.set_sql_cache(qh, sv, bv, result["sql"])
    return AskResponse(sql=result["sql"], cache_hit=False, retries_used=result["retries_used"])


@router.post("/{session_uuid}/execute", response_model=ExecuteResultResponse)
async def execute_query(session_uuid: str, payload: ExecuteRequest):
    """Run a user-reviewed SELECT and return rows as JSON (synchronous).

    Defense: validate first (fail-closed -- this catches SQL the user edited by
    hand, not just AI output), then execute ONLY inside run_sandboxed (rolled back,
    so even a validator bypass could not mutate data). Column names are recovered
    with a read-only DESCRIBE (run_sandboxed has none), and rows are capped at
    MAX_ROWS with a `truncated` flag. The documented async query_id/poll/MessagePack
    path (/queries/{id} below) stays deferred."""
    sql = (payload.sql or "").strip()
    if not sql_validator.validate(sql):
        raise HTTPException(
            status_code=400,
            detail="This query was rejected: only a single read-only SELECT is allowed.",
        )

    # S-1 (TASK-029): read-only is necessary but NOT sufficient on the shared
    # single-file DuckDB -- a bare SELECT can still read another tenant's table
    # or a file (read_csv_auto/read_text). Enforce that this query touches ONLY
    # this session's own tables and calls no filesystem/external function.
    scope_reason = sql_validator.scope_violation(sql, session_uuid)
    if scope_reason:
        raise HTTPException(
            status_code=400,
            detail=f"This query was rejected: it {scope_reason}.",
        )

    # Strip a trailing ';' so the statement can be wrapped as a subquery. (Stacked
    # statements were already rejected by the validator; this only tidies a lone
    # trailing terminator so `SELECT ...;` still runs.)
    inner = sql.rstrip(";").rstrip()

    try:
        # Column names/types: DESCRIBE is read-only and also sandboxed (rolled back).
        desc = await db_manager.run_sandboxed(f"DESCRIBE SELECT * FROM ({inner}) _q")
        # Rows, capped: fetch one extra to detect truncation.
        raw = await db_manager.run_sandboxed(f"SELECT * FROM ({inner}) _q LIMIT {MAX_ROWS + 1}")
    except Exception as exc:
        # A validated SELECT can still fail at run time (unknown column, type
        # mismatch). Surface it as a 400 for the editor to display.
        logger.info("execute: query failed at run time: %s", exc)
        raise HTTPException(status_code=400, detail=f"Query failed: {exc}")

    names = [r[0] for r in (desc or [])]
    types = [r[1] for r in (desc or [])]

    rows_raw = raw or []
    truncated = len(rows_raw) > MAX_ROWS
    if truncated:
        rows_raw = rows_raw[:MAX_ROWS]
    rows = [dict(zip(names, r)) for r in rows_raw]

    return ExecuteResultResponse(
        columns=[PreviewColumn(name=n, type=t) for n, t in zip(names, types)],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )


# --- Wave 4: AI batch (Foundation 2) -----------------------------------------
# Six features ride the one LiteLLM route pattern. Two shapes:
#   * SQL-producing (sql/assist fix|optimize) -> re-validated + sandbox-dry-run in
#     ai_service before return; the client still never auto-runs it (Review Gate).
#   * prose / advisory (explain, suggest, narrate, recommend, explain-chart) -> no
#     SQL is ever assembled from the inputs; they are prompt context only.
# All map AI errors uniformly via _llm_http (503 / 502 / 422).


@router.post("/{session_uuid}/sql/assist", response_model=SqlAssistResponse)
async def sql_assist(session_uuid: str, payload: SqlAssistRequest):
    """#22: explain / fix / optimize the SQL in the editor. `explain` returns prose
    only; `fix`/`optimize` return a NEW validated, dry-run-clean SELECT for the
    Review Gate (never executed here). The submitted SQL is untrusted -- fix/optimize
    output is re-validated exactly like /ask before it is returned."""
    sql = (payload.sql or "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="No SQL to act on.")

    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")
    bizdict = redis_manager.get_json(f"bizdict:{session_uuid}") or {}

    try:
        if payload.mode == "explain":
            explanation = await ai_service.explain_sql(sql, schema, bizdict)
            return SqlAssistResponse(mode="explain", sql=None, explanation=explanation, retries_used=0)
        result = await ai_service.rewrite_sql(payload.mode, sql, payload.error, schema, bizdict)
        return SqlAssistResponse(
            mode=payload.mode,
            sql=result["sql"],
            explanation=result["explanation"],
            retries_used=result["retries_used"],
        )
    except LLMError as exc:
        logger.warning("sql_assist(%s): %s", payload.mode, exc.message)
        raise _llm_http(exc)


@router.get("/{session_uuid}/suggest-questions", response_model=SuggestQuestionsResponse)
async def suggest_questions(session_uuid: str):
    """#26 auto-EDA: analytical questions answerable from the loaded schema, each
    ready to drop into /ask. Cached per schema_version (eda:{uuid}:{sv}), so a
    transform re-generates them but a repeat click is free."""
    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")

    sv = redis_manager.get_version(session_uuid)
    key = f"eda:{session_uuid}:{sv}"
    cached = redis_manager.get_json(key)
    if cached and cached.get("questions"):
        return SuggestQuestionsResponse(questions=cached["questions"], cache_hit=True)

    try:
        questions = await ai_service.suggest_questions(schema)
    except LLMError as exc:
        logger.warning("suggest_questions: %s", exc.message)
        raise _llm_http(exc)

    redis_manager.set_json(key, {"questions": questions})
    return SuggestQuestionsResponse(questions=questions, cache_hit=False)


@router.get("/{session_uuid}/narrate", response_model=NarrativeResponse)
async def narrate(session_uuid: str):
    """#29 data storytelling: a plain-prose overview of the loaded dataset. Cached
    per schema_version (story:{uuid}:{sv})."""
    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")

    sv = redis_manager.get_version(session_uuid)
    key = f"story:{session_uuid}:{sv}"
    cached = redis_manager.get_json(key)
    if cached and cached.get("narrative"):
        return NarrativeResponse(narrative=cached["narrative"], cache_hit=True)

    try:
        narrative = await ai_service.narrate_dataset(schema)
    except LLMError as exc:
        logger.warning("narrate: %s", exc.message)
        raise _llm_http(exc)

    redis_manager.set_json(key, {"narrative": narrative})
    return NarrativeResponse(narrative=narrative, cache_hit=False)


@router.post("/{session_uuid}/recommend-chart", response_model=RecommendChartResponse)
async def recommend_chart(session_uuid: str, payload: RecommendChartRequest):
    """#30: recommend a chart type (from the Canvas-supported set) for one column.
    The column name is prompt context only -- no SQL is built from it."""
    column = (payload.column or "").strip()
    if not column:
        raise HTTPException(status_code=400, detail="No column provided.")

    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")

    try:
        rec = await ai_service.recommend_chart(column, payload.column_type, payload.intent, schema)
    except LLMError as exc:
        logger.warning("recommend_chart: %s", exc.message)
        raise _llm_http(exc)

    return RecommendChartResponse(**rec)


@router.post("/{session_uuid}/explain-chart", response_model=NarrativeResponse)
async def explain_chart(session_uuid: str, payload: ExplainChartRequest):
    """#18: narrate one Canvas chart from the aggregate the client already holds. No
    new query runs; the keys/values are prompt context only."""
    schema = redis_manager.get_json(f"schema:{session_uuid}")
    if not schema:
        raise HTTPException(status_code=404, detail="No data loaded for this session.")

    spec = {
        "title": payload.title,
        "chart_type": payload.chart_type,
        "dimension": payload.dimension,
        "measure": payload.measure,
        "aggregation": payload.aggregation,
        "keys": payload.keys,
        "values": payload.values,
    }
    try:
        narrative = await ai_service.explain_chart(spec)
    except LLMError as exc:
        logger.warning("explain_chart: %s", exc.message)
        raise _llm_http(exc)

    return NarrativeResponse(narrative=narrative, cache_hit=False)


@router.get("/{session_uuid}/queries/{query_id}", response_model=QueryPollResponse)
async def poll_query(session_uuid: str, query_id: str):
    # Poll execution status/result -- part of the DEFERRED async /execute path
    # (query_id + MessagePack). /execute is synchronous JSON for Phase 6; this
    # stub is intentionally left intact so the async path can be built later.
    return QueryPollResponse(status="completed", result=b"")


@router.get("/{session_uuid}/instructions", response_model=List[CustomInstruction])
async def get_instructions(session_uuid: str):
    """List the session's business dictionary (bizdict:{session} -> {term: def})."""
    biz = redis_manager.get_json(f"bizdict:{session_uuid}") or {}
    return [CustomInstruction(term=t, definition=d) for t, d in biz.items()]


@router.post("/{session_uuid}/instructions")
async def add_instruction(session_uuid: str, payload: CustomInstruction):
    """Add/update one term. Bumps bizdict_version so any AI SQL cached against the
    old dictionary is invalidated (the term may change what a question means)."""
    term = (payload.term or "").strip()
    definition = (payload.definition or "").strip()
    if not term or not definition:
        raise HTTPException(status_code=400, detail="Both term and definition are required.")

    biz = redis_manager.get_json(f"bizdict:{session_uuid}") or {}
    biz[term] = definition
    redis_manager.set_json(f"bizdict:{session_uuid}", biz)
    redis_manager.incr_bizdict_version(session_uuid)
    return {"status": "added", "term": term}


@router.delete("/{session_uuid}/instructions/{term}")
async def delete_instruction(session_uuid: str, term: str):
    """Remove a term. Bumps bizdict_version (same invalidation reason as add)."""
    biz = redis_manager.get_json(f"bizdict:{session_uuid}") or {}
    if term not in biz:
        raise HTTPException(status_code=404, detail=f"Term '{term}' not found.")
    del biz[term]
    redis_manager.set_json(f"bizdict:{session_uuid}", biz)
    redis_manager.incr_bizdict_version(session_uuid)
    return {"status": "deleted", "term": term}
