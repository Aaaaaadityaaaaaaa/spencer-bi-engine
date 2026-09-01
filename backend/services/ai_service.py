"""NL->SQL generation for the Query Engine (Phase 6).

This is the dormant middle of the AI path that ARCHITECTURE.md describes, now
wired. It turns a natural-language question + the session's schema/business
dictionary into a single read-only DuckDB SELECT, using a self-correcting loop:

    generate  ->  extract SQL  ->  sql_validator.validate (defense layer 1)
              ->  safe sandboxed dry-run (rolled back; catches real DuckDB errors)
              ->  on error, feed the classified failure back and retry (bounded at 3)

The LLM call goes through **LiteLLM** (`litellm.acompletion`), so one code path
routes to Claude *or* Gemini depending on which API key is present in the env --
no provider-specific SDK wiring here. Keys are read from the environment by
LiteLLM itself (ANTHROPIC_API_KEY / GEMINI_API_KEY); nothing is hardcoded.

This module NEVER executes SQL for real: `run_sandboxed` wraps the dry-run in an
unconditional-rollback transaction (ADR-010), and even that only runs *after*
`sql_validator` has passed. Actually returning rows to the user is the router's
`/execute` (which validates again -- the user may have edited the SQL). This path
is explicitly NOT Ibis (ADR-007): AI-generated SQL is free-form text, which is
exactly what the validator + sandbox exist to contain.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from services.duckdb_manager import db_manager
from services.sql_validator import sql_validator
from services.llm_key_pool import llm_key_pool
from config import LLM_KEY_COOLDOWN_SECONDS, LLM_DAILY_COOLDOWN_SECONDS

logger = logging.getLogger("spencer.ai")

# LiteLLM is an optional-at-import dependency: if it is missing we still want the
# rest of the AI router (/execute, /instructions) to work, so we degrade to a
# clean LLMConfigError at call time instead of crashing the app on import.
try:
    import litellm

    litellm.suppress_debug_info = True
    litellm.drop_params = True  # silently ignore params a given provider doesn't accept
except Exception:  # pragma: no cover - exercised only when the dep is absent
    litellm = None

# Bounded self-correction (ARCHITECTURE.md): at most this many LLM attempts for
# one question before we give up and cache the failure.
MAX_ATTEMPTS = 3

# Sensible, overridable defaults. SPENCER_LLM_MODEL wins if set; otherwise the
# provider is chosen by whichever key is present. Model ids are LiteLLM-style
# ("<provider>/<model>"). Override in .env if your account exposes different ids.
_DEFAULT_ANTHROPIC_MODEL = "anthropic/claude-sonnet-5"
# gemini-2.5-flash is retired for accounts created after its EOL (the API returns
# 404 "no longer available to new users"); 3.6-flash is the current flash tier.
_DEFAULT_GEMINI_MODEL = "gemini/gemini-3.6-flash"

# Thinking/reasoning budget for the call. The current flash tier is a "thinking" model
# that, left to its default budget, spends many seconds reasoning before emitting even a
# short answer -- so a 5-question suggestion took ~20s. Every AI task here is narrow and
# structured (propose questions, write one SELECT, pick a chart), none needs deep chain-
# of-thought, so we cap thinking to a small budget. LiteLLM maps `reasoning_effort` to
# each provider's native control (Gemini thinkingConfig, Anthropic thinking budget); with
# drop_params=True a provider that doesn't support it silently ignores it. Override with
# SPENCER_LLM_REASONING_EFFORT: minimal|low|medium|high, or "default"/"" to send nothing
# (restore the provider's own default). Kept conservative at "low" -- fast, still coherent.
_REASONING_EFFORT = os.getenv("SPENCER_LLM_REASONING_EFFORT", "low").strip().lower()

_SYSTEM_PROMPT = (
    "You are a text-to-SQL generator for a DuckDB database. Given a schema and a "
    "question, return exactly ONE read-only SQL SELECT statement that answers it.\n"
    "Rules:\n"
    "- Output ONLY the SQL. No prose, no explanation, no markdown code fences.\n"
    "- It MUST be a single SELECT (common table expressions are allowed). Never "
    "emit INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, COPY, ATTACH, or any other "
    "statement that writes or changes state.\n"
    "- Use only the tables and columns shown in the schema. Use DuckDB SQL syntax.\n"
    '- Quote identifiers with double quotes when they contain spaces or special '
    "characters."
)

# --- Wave 4 assistants (Foundation 2) ----------------------------------------
# Each prompt is deliberately narrow and single-purpose. The two SQL-producing
# modes (fix, optimize) emit STRICT JSON {sql, explanation}; their sql is then
# re-validated + dry-run exactly like _SYSTEM_PROMPT output before it is returned.

_EXPLAIN_SQL_SYSTEM = (
    "You explain DuckDB SQL to a data analyst. Given a schema and a query, describe in "
    "2-4 short sentences what the query returns and any notable clauses (joins, filters, "
    "grouping, ordering, limits). Be concrete about the columns and aggregations "
    "involved. Output PLAIN PROSE only -- no markdown, no code fences, no bullet lists, "
    "no SQL."
)

_FIX_SQL_SYSTEM = (
    "You fix a failing DuckDB SQL query. You are given the schema, the query, and the "
    "DuckDB error it produced. Return a corrected query that answers the same intent.\n"
    "Rules:\n"
    "- The result MUST be a single read-only SELECT (CTEs allowed). Never emit INSERT, "
    "UPDATE, DELETE, DROP, CREATE, ALTER, COPY, ATTACH or any state-changing statement.\n"
    "- Use ONLY tables and columns shown in the schema. Use DuckDB syntax.\n"
    "- Respond with STRICT JSON only (no markdown fences): "
    '{"sql": "<the corrected SELECT>", "explanation": "<one or two sentences on what was '
    'wrong and what you changed>"}.'
)

_OPTIMIZE_SQL_SYSTEM = (
    "You improve a DuckDB SQL query for clarity and efficiency WITHOUT changing which "
    "rows it returns. Prefer simpler, standard DuckDB constructs. If the query is already "
    "good, return it essentially unchanged and say so.\n"
    "Rules:\n"
    "- The result MUST be a single read-only SELECT (CTEs allowed); never a write.\n"
    "- Use ONLY tables and columns shown in the schema. Use DuckDB syntax.\n"
    "- Respond with STRICT JSON only (no markdown fences): "
    '{"sql": "<the improved SELECT>", "explanation": "<one or two sentences on what you '
    'changed and why, or that it was already optimal>"}.'
)

_SUGGEST_SYSTEM = (
    "You are a data analyst proposing exploratory questions about a dataset. Given the "
    "schema (tables, columns, sample values), propose FIVE distinct, specific, "
    "business-relevant questions that can EACH be answered by a single SQL SELECT over "
    "this data. Favour aggregations, groupings, trends and rankings that suit the actual "
    "columns. Never reference a column that is not in the schema.\n"
    "Respond with STRICT JSON only (no markdown fences): an array of exactly five short "
    'question strings, e.g. ["What is total revenue by region?", "..."]'
)

_NARRATE_DATASET_SYSTEM = (
    "You are a data analyst writing a brief, plain-language overview of a dataset for a "
    "business reader. Given the schema (tables, columns, types, sample values), describe "
    "in 3-5 sentences what this dataset appears to contain, what one row represents, the "
    "kinds of analysis it supports, and any obvious caveats. Do not invent specific "
    "numbers you were not given. Output PLAIN PROSE only -- no markdown, no headings, no "
    "bullet lists."
)

_RECOMMEND_CHART_SYSTEM = (
    "You recommend a chart type for visualising a single column from a dataset, for a "
    "dashboard that supports EXACTLY these chart types: bar, line, area, hbar (horizontal "
    "bar), pie. Consider the column's name, type and the user's stated intent if any. Pick "
    "the single best fit plus up to two alternatives, all from that supported set.\n"
    "Respond with STRICT JSON only (no markdown fences): "
    '{"chart_type": "<one of bar|line|area|hbar|pie>", "reasoning": "<one or two '
    'sentences>", "alternatives": ["<other supported types>"]}'
)

_EXPLAIN_CHART_SYSTEM = (
    "You explain what a single dashboard chart shows to a business reader. You are given "
    "the chart's type, its dimension and measure, the aggregation, and the aggregated data "
    "points (category -> value). Describe in 2-4 sentences what the chart shows, the most "
    "notable point(s) (largest / smallest, any clear trend or skew), and what it means in "
    "plain terms. Use ONLY the numbers provided; never invent data. Output PLAIN PROSE "
    "only -- no markdown, no bullet lists."
)


class LLMError(Exception):
    """Base for AI-path failures. Carries a stable `code` and a `retryable` hint
    the router turns into the uniform ErrorResponse{error, message, retryable}."""

    code = "llm_error"
    retryable = False

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def as_error(self) -> Dict[str, Any]:
        return {"error": self.code, "message": self.message, "retryable": self.retryable}


class LLMConfigError(LLMError):
    """No usable model/key (or litellm not installed). Retrying won't help until
    the operator configures a provider, so this is NOT retryable."""

    code = "llm_not_configured"
    retryable = False


class LLMAPIError(LLMError):
    """The provider call itself failed (network/timeout/rate-limit). This is a
    distinct mode from 'the model produced bad SQL' -- it does not consume a
    self-correction attempt, and the user may simply try again."""

    code = "llm_api_error"
    retryable = True


class LLMRateLimitError(LLMAPIError):
    """Every key in the provider's pool is currently rate-limited / quota-exhausted
    (TASK-024). A subclass of LLMAPIError, so any pre-existing `except LLMAPIError`
    still degrades safely to a 502; routers/ai.py upgrades it to a 429 + Retry-After.
    `retry_after` is the best-effort soonest number of seconds until a key frees up."""

    code = "llm_rate_limited"
    retryable = True

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMResolveError(LLMError):
    """The bounded loop finished without a valid, runnable SELECT. Rewording the
    question (or adding a Custom Instruction) may help, so it is retryable."""

    code = "sql_generation_failed"
    retryable = True


# --- 429 classification for the key pool (TASK-024) --------------------------
# Pull a retry hint ("retryDelay": "33s", or retry_delay { seconds: 33 }) out of a 429
# message; grab the first number after the marker so both shapes parse.
_RETRY_DELAY_RE = re.compile(r"retry[_-]?delay\D*?(\d+)", re.IGNORECASE)
# Substrings that mark a per-DAY quota (long bench) vs a per-minute burst (short bench).
_DAILY_MARKERS = ("perday", "per_day", "/day", "free_tier_requests")


class _RateLimitSignal(Exception):
    """Internal-only: one provider call was rate-limited (429). Carries how long to
    bench the key (`cooldown_s`), the raw `retry_after` hint, and whether it was a
    per-DAY quota. Never escapes `_call_llm` -- it is caught there and turned into a
    key rotation or, when the pool is exhausted, an LLMRateLimitError."""

    def __init__(self, cooldown_s: int, retry_after: int, is_daily: bool):
        super().__init__("rate limited")
        self.cooldown_s = cooldown_s
        self.retry_after = retry_after
        self.is_daily = is_daily


def _is_rate_limit(exc: Exception) -> bool:
    """True if a LiteLLM completion exception is a 429 / rate-limit, OR a 50x 
    Service Unavailable / timeout error. By classifying 503s here, the key pool 
    will instantly rotate to the next API key (which often routes to a different 
    node/region) instead of hard-failing."""
    status = getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
        
    if litellm is not None:
        rle = getattr(litellm, "RateLimitError", None)
        if rle is not None and isinstance(exc, rle):
            return True
        # LiteLLM explicitly throws ServiceUnavailableError for 503
        sue = getattr(litellm, "ServiceUnavailableError", None)
        if sue is not None and isinstance(exc, sue):
            return True
            
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "serviceunavailable" in name or "timeout" in name


def _rate_limit_signal(exc: Exception) -> "_RateLimitSignal":
    """Classify a 429 into a bench duration. A per-DAY quota parks the key for
    LLM_DAILY_COOLDOWN_SECONDS (self-heals across the provider's midnight reset); a
    per-minute limit uses the parsed retryDelay, falling back to LLM_KEY_COOLDOWN_SECONDS."""
    msg = str(exc)
    low = msg.lower()
    is_daily = any(m in low for m in _DAILY_MARKERS)
    m = _RETRY_DELAY_RE.search(msg)
    retry_after = int(m.group(1)) if m else LLM_KEY_COOLDOWN_SECONDS
    cooldown_s = LLM_DAILY_COOLDOWN_SECONDS if is_daily else retry_after
    return _RateLimitSignal(cooldown_s=cooldown_s, retry_after=retry_after, is_daily=is_daily)


def _extract_sql(text: str) -> str:
    """Pull a bare SQL statement out of an LLM reply that may include fences or
    prose. Over-extraction is safe: anything malformed is caught by
    sql_validator (fail-closed) and simply triggers a retry, never execution."""
    s = (text or "").strip()

    # Prefer the contents of the first fenced code block if present.
    fence = re.search(r"```(?:sql)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()

    # If prose precedes the query, slice from the first SELECT / WITH.
    kw = re.search(r"\b(WITH|SELECT)\b", s, re.IGNORECASE)
    if kw:
        s = s[kw.start():]

    # Keep only the first statement: drop a trailing ';' and anything after it.
    # (Statement stacking is also rejected by the validator; this is belt-and-braces.)
    semi = s.find(";")
    if semi != -1:
        s = s[:semi]

    return s.strip()


def _extract_json(text: str) -> Any:
    """Parse a JSON object/array out of an LLM reply that may wrap it in prose or a
    ```json fence. Tries the whole string, then the fenced block, then the widest
    bracket-to-bracket slice. Raises LLMResolveError (retryable) if nothing parses,
    so a malformed reply is surfaced cleanly rather than crashing the route."""
    s = (text or "").strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()

    try:
        return json.loads(s)
    except Exception:
        pass

    # Slice from the first opening bracket to the last matching closing bracket.
    candidates = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if candidates:
        start = min(candidates)
        end_char = "}" if s[start] == "{" else "]"
        end = s.rfind(end_char)
        if end > start:
            try:
                return json.loads(s[start : end + 1])
            except Exception:
                pass

    raise LLMResolveError(
        "The model did not return usable structured output. Please try again."
    )
    """Turn a raw DuckDB error from the dry-run into a targeted hint for the next
    attempt. Distinguishes a missing column (append guidance to stick to the
    schema), an identical repeat (nudge a different approach), and everything
    else (pass the error through)."""
    low = err.lower()
    if "column" in low and ("not found" in low or "does not exist" in low or "referenced" in low):
        return (
            f"The previous query failed because a column was not found: {err}. "
            "Use ONLY columns that appear in the schema above."
        )
    if prev_sql is not None and prev_sql == sql:
        return "That produced the same failing query again. Try a genuinely different approach."
    return f"The previous query failed with a DuckDB error: {err}. Fix it."


class AIService:
    def _resolve_model(self) -> str:
        """Pick the LiteLLM model id: explicit override, else by available key.
        Raises LLMConfigError when nothing is configured."""
        explicit = os.getenv("SPENCER_LLM_MODEL")
        if explicit:
            return explicit
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEYS"):
            return _DEFAULT_ANTHROPIC_MODEL
        if os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"):
            return _DEFAULT_GEMINI_MODEL
        raise LLMConfigError(
            "No LLM provider configured. Set ANTHROPIC_API_KEY or GEMINI_API_KEY "
            "(or SPENCER_LLM_MODEL) in the backend environment."
        )

    def _schema_context(self, schema: Dict[str, Any]) -> Tuple[str, str]:
        """Render the cached `schema:{session}` dict into (ddl_block, samples_block)
        for the prompt. `schema` is {table_name: {ddl, cardinality, samples, ...}}."""
        ddls, sample_lines = [], []
        for tname, ctx in (schema or {}).items():
            if not isinstance(ctx, dict):
                continue
            ddl = ctx.get("ddl")
            if ddl:
                ddls.append(str(ddl))
            for col, vals in (ctx.get("samples") or {}).items():
                if not vals:
                    continue
                preview = ", ".join(str(v) for v in vals[:10])
                sample_lines.append(f"  {tname}.{col}: {preview}")
        return "\n".join(ddls), "\n".join(sample_lines)

    def _build_user_prompt(
        self,
        question: str,
        schema: Dict[str, Any],
        bizdict: Dict[str, Any],
        prev_sql: Optional[str],
        prev_error: Optional[str],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        ddl_block, samples_block = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)"]
        if samples_block:
            parts += ["", "Sample values for low-cardinality columns:", samples_block]
        if bizdict:
            defs = "\n".join(f"  {term}: {definition}" for term, definition in bizdict.items())
            parts += ["", "Business definitions (apply these when relevant):", defs]
        if history:
            # #21 conversational refinement: prior (question -> SQL) turns so the
            # current question can be read as a follow-up ("now group by month").
            hist_lines: List[str] = []
            for turn in history:
                q = (turn.get("question") or "").strip()
                s = (turn.get("sql") or "").strip()
                if q:
                    hist_lines.append(f"Q: {q}")
                if s:
                    hist_lines.append(f"SQL: {s}")
            if hist_lines:
                parts += [
                    "",
                    "Earlier in this conversation (oldest first):",
                    *hist_lines,
                    "",
                    'The user now asks a FOLLOW-UP that may refer to the previous query '
                    '(e.g. "that", "now group by month", "same but top 5"). Refine the '
                    "previous SQL when the follow-up implies it; otherwise answer fresh.",
                ]
        parts += ["", f"Question: {question}"]
        if prev_sql is not None and prev_error:
            parts += [
                "",
                "Your previous attempt was:",
                prev_sql,
                f"It was rejected: {prev_error}",
                "Return a corrected single read-only SELECT (SQL only).",
            ]
        return "\n".join(parts)

    async def _one_call(self, model: str, messages: list, api_key: Optional[str]) -> str:
        """One raw LiteLLM completion with an explicit (optional) api_key. Classifies a
        429 into a _RateLimitSignal (so the caller can rotate keys); any other transport
        failure or a malformed response becomes an LLMAPIError -- verbatim today's
        behaviour for the non-rate-limit paths."""
        try:
            extra: Dict[str, Any] = {}
            # Pass a bounded thinking budget unless explicitly disabled. drop_params=True
            # means a provider that doesn't understand reasoning_effort just ignores it.
            if _REASONING_EFFORT and _REASONING_EFFORT not in ("default", "none", "off", ""):
                extra["reasoning_effort"] = _REASONING_EFFORT
            resp = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=1024,
                api_key=api_key,
                **extra,
            )
        except Exception as exc:
            if _is_rate_limit(exc):
                raise _rate_limit_signal(exc) from exc
            logger.warning("LLM API call failed (%s): %s", type(exc).__name__, exc)
            raise LLMAPIError(f"The language model request failed: {exc}") from exc
        try:
            return resp.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - defensive
            raise LLMAPIError(f"Unexpected LLM response shape: {exc}") from exc

    async def _call_model_with_pool(self, model: str, system: str, user: str) -> str:
        """One logical LLM completion, transparently rotated across the provider's key
        pool (TASK-024).

        No pool for the provider -> byte-identical to the pre-pool path: a single call
        with api_key=None (LiteLLM reads the env), any failure -> LLMAPIError (502).

        Pool present -> a 429 benches that key in Redis (long for a per-DAY quota, short
        for a per-minute burst) and the next healthy key retries; only when every key is
        spent is LLMRateLimitError raised (routers/ai.py -> a clean, retryable 429). A
        non-429 error bubbles immediately so a transport blip never burns the whole pool."""
        if litellm is None:
            raise LLMConfigError("litellm is not installed on the backend.")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        provider = model.split("/", 1)[0]

        # No pool configured for this provider -> preserve the exact single-key path.
        if not llm_key_pool.has_keys(provider):
            return await self._one_call(model, messages, None)

        # Pool path: at most one lap of the ring; each 429 benches its key so the next
        # acquire() skips it, and the loop is bounded by the number of keys.
        soonest: Optional[int] = None
        attempts = 0
        max_attempts = llm_key_pool.size(provider)
        while attempts < max_attempts:
            picked = llm_key_pool.acquire(provider)
            if picked is None:
                break  # every key is cooling down / over its daily cap
            keyid, key = picked
            attempts += 1
            try:
                content = await self._one_call(model, messages, key)
            except _RateLimitSignal as sig:
                llm_key_pool.record_rate_limited(provider, keyid, sig.cooldown_s)
                soonest = sig.retry_after if soonest is None else min(soonest, sig.retry_after)
                logger.warning(
                    "llm_key_pool: %s key %s rate-limited (%s); benched %ds, rotating",
                    provider,
                    llm_key_pool._mask(key),
                    "per-day" if sig.is_daily else "per-minute",
                    sig.cooldown_s,
                )
                continue
            # Success. (A non-429 error was already raised as LLMAPIError by _one_call
            # and propagates out of this loop without benching a key.)
            llm_key_pool.record_success(provider, keyid)
            return content

        wait = soonest if soonest is not None else LLM_KEY_COOLDOWN_SECONDS
        raise LLMRateLimitError(
            f"All {max_attempts} API key(s) for {provider} are rate-limited. "
            f"Try again in ~{wait}s.",
            retry_after=wait,
        )

    async def _call_llm(self, primary_model: str, system: str, user: str) -> str:
        """Entrypoint for LLM completions with fallback chain support.
        
        Attempts the primary model (with key rotation via _call_model_with_pool).
        If exhausted or failed, gracefully moves to models in SPENCER_LLM_FALLBACK_MODELS.
        """
        models = [primary_model]
        fallbacks = os.environ.get("SPENCER_LLM_FALLBACK_MODELS", "")
        if fallbacks:
            models.extend([m.strip() for m in fallbacks.split(",") if m.strip()])

        last_err = None
        soonest = None
        
        for model in models:
            try:
                return await self._call_model_with_pool(model, system, user)
            except LLMConfigError as e:
                last_err = e
                logger.warning("llm fallback: model '%s' misconfigured or missing litellm (%s), trying next", model, e)
                continue
            except LLMRateLimitError as e:
                last_err = e
                # Fallback on rate limit
                soonest = e.retry_after if soonest is None else min(soonest, e.retry_after)
                logger.warning("llm fallback: model '%s' rate-limited, trying next", model)
                continue
            except LLMAPIError as e:
                last_err = e
                # Fallback on transport/auth error
                logger.warning("llm fallback: model '%s' API error (%s), trying next", model, e)
                continue

        if isinstance(last_err, LLMRateLimitError):
            raise LLMRateLimitError(
                "All AI models in the fallback chain are exhausted or rate-limited.",
                retry_after=soonest or 60,
            )
        if last_err:
            raise last_err
            
        raise LLMConfigError("No valid LLM models configured in the fallback chain.")

    async def resolve_sql(
        self,
        question: str,
        schema: Dict[str, Any],
        bizdict: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Generate a validated, dry-run-clean SELECT for `question`.

        `history` (optional, #21) is prior (question, sql) turns so a follow-up
        refines the last query. Returns {"sql": <str>, "retries_used": <int>} where
        retries_used is the number of extra attempts beyond the first (0 => first
        try worked).

        Raises LLMConfigError (no provider), LLMAPIError (provider call failed --
        surfaced immediately, not retried as bad SQL), or LLMResolveError (the
        bounded loop could not produce runnable SQL)."""
        model = self._resolve_model()
        last_sql: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(MAX_ATTEMPTS):
            user_prompt = self._build_user_prompt(
                question, schema, bizdict, last_sql, last_error, history
            )
            raw = await self._call_llm(model, _SYSTEM_PROMPT, user_prompt)  # LLMAPIError propagates
            sql = _extract_sql(raw)

            # Defense layer 1: must be a single, pure, read-only SELECT.
            if not sql or not sql_validator.validate(sql):
                last_error = (
                    "That was rejected by the safety validator (it must be a single "
                    "read-only SELECT with no writes)."
                )
                last_sql = sql or last_sql
                logger.info("ai attempt %d rejected by validator", attempt)
                continue

            # Defense layer 2 (used here as a safe dry-run): execute inside a
            # transaction that is ALWAYS rolled back, so a syntactically-valid but
            # semantically-wrong query (bad column, type mismatch) is caught now
            # rather than surfacing later, and nothing is ever committed.
            try:
                await db_manager.run_sandboxed(sql)
            except Exception as exc:
                last_error = _classify_db_error(str(exc), last_sql, sql)
                last_sql = sql
                logger.info("ai attempt %d failed dry-run: %s", attempt, exc)
                continue

            return {"sql": sql, "retries_used": attempt}

        raise LLMResolveError(
            "Could not generate valid SQL for that question after several attempts. "
            "Try rewording it, or add a Custom Instruction to clarify a term."
        )

    async def generate_sql(
        self,
        question: str,
        schema: Dict[str, Any],
        bizdict: Dict[str, Any],
        attempt: int = 0,
    ) -> str:
        """Single-attempt shim kept for the documented signature (ARCHITECTURE.md).
        `resolve_sql` owns the self-correcting loop and is what the router calls."""
        model = self._resolve_model()
        raw = await self._call_llm(
            model, _SYSTEM_PROMPT, self._build_user_prompt(question, schema, bizdict, None, None)
        )
        return _extract_sql(raw)

    # --- Wave 4 assistants ---------------------------------------------------

    def _defs_block(self, bizdict: Dict[str, Any]) -> List[str]:
        """Render the business dictionary into prompt lines (empty when absent)."""
        if not bizdict:
            return []
        defs = "\n".join(f"  {t}: {d}" for t, d in bizdict.items())
        return ["", "Business definitions (apply these when relevant):", defs]

    async def _check_sql(self, sql: str) -> Optional[str]:
        """Return None if `sql` is a valid, dry-run-clean read-only SELECT, else a
        short error string. Same two defense layers as resolve_sql (validator +
        rolled-back sandbox), reused by the SQL-producing assistants."""
        if not sql or not sql_validator.validate(sql):
            return "It was not a single read-only SELECT (rejected by the safety validator)."
        try:
            await db_manager.run_sandboxed(sql)
        except Exception as exc:
            return f"It failed a DuckDB dry-run: {exc}"
        return None

    async def explain_sql(
        self, sql: str, schema: Dict[str, Any], bizdict: Dict[str, Any]
    ) -> str:
        """#22 (explain): plain-prose description of what a query does. Read-only;
        the SQL is context, never executed here."""
        model = self._resolve_model()
        ddl_block, _ = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)"]
        parts += self._defs_block(bizdict)
        parts += ["", "Explain this query:", sql]
        raw = await self._call_llm(model, _EXPLAIN_SQL_SYSTEM, "\n".join(parts))
        text = (raw or "").strip()
        if not text:
            raise LLMResolveError("The model returned an empty explanation.")
        return text

    def _build_rewrite_prompt(
        self,
        mode: str,
        sql: str,
        error: Optional[str],
        schema: Dict[str, Any],
        bizdict: Dict[str, Any],
        prev_sql: Optional[str],
        prev_error: Optional[str],
    ) -> str:
        ddl_block, samples_block = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)"]
        if samples_block:
            parts += ["", "Sample values for low-cardinality columns:", samples_block]
        parts += self._defs_block(bizdict)
        parts += ["", f"The query to {mode}:", sql]
        if mode == "fix" and (error or "").strip():
            parts += ["", f"DuckDB error it produced: {error.strip()}"]
        if prev_sql is not None and prev_error:
            parts += [
                "",
                "Your previous attempt was:",
                prev_sql,
                f"It was rejected: {prev_error}",
                "Return corrected STRICT JSON {sql, explanation}.",
            ]
        return "\n".join(parts)

    async def rewrite_sql(
        self,
        mode: str,
        sql: str,
        error: Optional[str],
        schema: Dict[str, Any],
        bizdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """#22 (fix / optimize): return a NEW, validated, dry-run-clean SELECT plus a
        one-line explanation. Bounded self-correction loop identical in spirit to
        resolve_sql, but the model emits JSON {sql, explanation}. The returned SQL is
        for the Review Gate -- the router never auto-runs it.

        Returns {"sql": <str>, "explanation": <str>, "retries_used": <int>}."""
        model = self._resolve_model()
        system = _FIX_SQL_SYSTEM if mode == "fix" else _OPTIMIZE_SQL_SYSTEM
        last_sql: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(MAX_ATTEMPTS):
            user = self._build_rewrite_prompt(
                mode, sql, error, schema, bizdict, last_sql, last_error
            )
            raw = await self._call_llm(model, system, user)  # LLMAPIError propagates
            data = _extract_json(raw)
            if not isinstance(data, dict):
                last_error = "Output was not a JSON object with sql/explanation."
                logger.info("ai %s attempt %d: non-object JSON", mode, attempt)
                continue
            new_sql = _extract_sql(str(data.get("sql", "")))
            explanation = str(data.get("explanation") or "").strip()

            check = await self._check_sql(new_sql)
            if check is None:
                return {
                    "sql": new_sql,
                    "explanation": explanation or "Rewrote the query.",
                    "retries_used": attempt,
                }
            last_sql = new_sql or last_sql
            last_error = check
            logger.info("ai %s attempt %d rejected: %s", mode, attempt, check)

        raise LLMResolveError(
            "Could not produce a valid corrected query after several attempts."
        )

    async def suggest_questions(self, schema: Dict[str, Any]) -> List[str]:
        """#26 auto-EDA: propose analytical questions answerable from the schema.
        Returns a list of question strings (deduped, capped)."""
        model = self._resolve_model()
        ddl_block, samples_block = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)"]
        if samples_block:
            parts += ["", "Sample values for low-cardinality columns:", samples_block]
        parts += ["", "Propose five questions."]
        raw = await self._call_llm(model, _SUGGEST_SYSTEM, "\n".join(parts))
        data = _extract_json(raw)
        if not isinstance(data, list):
            raise LLMResolveError("The model did not return a list of questions.")
        seen, questions = set(), []
        for q in data:
            text = str(q).strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                questions.append(text)
        if not questions:
            raise LLMResolveError("The model returned no questions.")
        return questions[:6]

    async def narrate_dataset(self, schema: Dict[str, Any]) -> str:
        """#29 data storytelling: a plain-prose overview of the loaded dataset."""
        model = self._resolve_model()
        ddl_block, samples_block = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)"]
        if samples_block:
            parts += ["", "Sample values for low-cardinality columns:", samples_block]
        parts += ["", "Write the overview."]
        raw = await self._call_llm(model, _NARRATE_DATASET_SYSTEM, "\n".join(parts))
        text = (raw or "").strip()
        if not text:
            raise LLMResolveError("The model returned an empty narrative.")
        return text

    async def recommend_chart(
        self,
        column: str,
        column_type: Optional[str],
        intent: Optional[str],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """#30: recommend a chart type (from the Canvas-supported set) for one column.
        chart_type/alternatives are constrained to the supported set server-side, so
        the UI can trust them; a model reply outside the set falls back to 'bar'."""
        model = self._resolve_model()
        ddl_block, _ = self._schema_context(schema)
        parts = ["Schema (DuckDB):", ddl_block or "(no tables)", ""]
        head = f"Column to visualise: {column}"
        if column_type:
            head += f" (type {column_type})"
        parts.append(head)
        if (intent or "").strip():
            parts.append(f"User intent: {intent.strip()}")
        raw = await self._call_llm(model, _RECOMMEND_CHART_SYSTEM, "\n".join(parts))
        data = _extract_json(raw)
        if not isinstance(data, dict):
            raise LLMResolveError("The model did not return a chart recommendation object.")

        supported = {"bar", "line", "area", "hbar", "pie"}
        ct = str(data.get("chart_type", "")).strip().lower()
        if ct not in supported:
            ct = "bar"  # advisory fallback; UI still maps it onto a real picker value
        alts = []
        for a in data.get("alternatives") or []:
            av = str(a).strip().lower()
            if av in supported and av != ct and av not in alts:
                alts.append(av)
        reasoning = str(data.get("reasoning") or "").strip() or f"A {ct} chart suits this column."
        return {"chart_type": ct, "reasoning": reasoning, "alternatives": alts[:2]}

    async def explain_chart(self, spec: Dict[str, Any]) -> str:
        """#18: narrate one Canvas chart from the aggregate the client already holds.
        `spec` = {title, chart_type, dimension, measure, aggregation, keys[], values[]}."""
        model = self._resolve_model()
        keys = spec.get("keys") or []
        values = spec.get("values") or []
        pairs = [f"  {k}: {v}" for k, v in list(zip(keys, values))[:50]]
        parts = [
            f"Chart title: {spec.get('title') or '(none)'}",
            f"Chart type: {spec.get('chart_type')}",
            f"Dimension (category / x-axis): {spec.get('dimension') or '(none)'}",
            f"Measure: {spec.get('measure') or '(row count)'}",
            f"Aggregation: {spec.get('aggregation')}",
            "Data points (category: value):",
            "\n".join(pairs) if pairs else "  (no data)",
        ]
        raw = await self._call_llm(model, _EXPLAIN_CHART_SYSTEM, "\n".join(parts))
        text = (raw or "").strip()
        if not text:
            raise LLMResolveError("The model returned an empty explanation.")
        return text


ai_service = AIService()
