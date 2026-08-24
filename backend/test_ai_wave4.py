"""Wave 4 (AI batch) — offline unit proof for the six new AI-service assistants
and the /ask cache-hash change.

The whole point of this file is to test the ORCHESTRATION logic (prompt assembly,
JSON extraction, SQL re-validation, self-correction, dedup, fallbacks, error
mapping) WITHOUT making a real LLM call or touching DuckDB. So three external
effects are monkeypatched on the shared singletons:

  * ai_service._resolve_model  -> returns a fake model id (no env/key dependency)
  * ai_service._call_llm       -> returns canned responses from a queue
  * db_manager.run_sandboxed   -> simulates a dry-run (optionally failing)

Everything else under test is the REAL code: _extract_json, _extract_sql,
sql_validator.validate (fail-closed), the bounded rewrite loop, and the router's
_ask_cache_hash. No uvicorn required; safe to run while the backend is stopped.

Run:  python backend/test_ai_wave4.py   (from repo root or backend/)
"""

import asyncio
import os
import sys

# Make `services` / `routers` importable regardless of cwd, and prefer the real
# Redis on :6380 so the AP-9 backend announcement is accurate (these tests don't
# actually exercise Redis; the announcement is for convention/proof parity).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("REDIS_PORT", "6380")

# Windows consoles default to cp1252, which can't encode the ✔/✘ marks; force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.ai_service import (  # noqa: E402
    ai_service,
    _extract_json,
    _extract_sql,
    LLMResolveError,
)
from services.duckdb_manager import db_manager  # noqa: E402
from services.redis_manager import redis_manager  # noqa: E402
from routers.ai import _ask_cache_hash, _question_hash  # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✔ {label}")
    else:
        FAIL += 1
        print(f"  ✘ {label} — {detail}")


# --- Monkeypatched external effects ------------------------------------------

class _LLM:
    queue = []          # responses served in order by fake_call_llm
    calls = []          # (model, system, user) recorded per call


async def fake_call_llm(model, system, user):
    # Bound as an instance attribute, so NO self is passed (matches call site).
    _LLM.calls.append((model, system, user))
    return _LLM.queue.pop(0) if _LLM.queue else ""


class _SB:
    fail_substr = None  # if set, run_sandboxed raises for any sql containing it
    calls = []


async def fake_sandboxed(sql):
    _SB.calls.append(sql)
    if _SB.fail_substr and _SB.fail_substr in sql:
        raise Exception('Binder Error: Referenced column "bad_col" not found')
    return []


def set_llm(*responses):
    _LLM.queue = list(responses)
    _LLM.calls = []


def install_patches():
    ai_service._resolve_model = lambda: "test/model-offline"
    ai_service._call_llm = fake_call_llm
    db_manager.run_sandboxed = fake_sandboxed


async def expect_raises(exc_type, coro):
    try:
        await coro
    except exc_type:
        return True
    except Exception as e:  # wrong exception type
        print(f"     (raised {type(e).__name__} instead)")
        return False
    return False


# Schema shaped like the cached schema:{session} dict.
SCHEMA = {
    "sales": {
        "ddl": 'CREATE TABLE sales("id" INTEGER, "region" VARCHAR, "product" VARCHAR, "revenue" DOUBLE)',
        "samples": {"region": ["North", "South", "East", "West"]},
    }
}
GOOD_SQL = 'SELECT "region", SUM("revenue") AS total FROM sales GROUP BY "region"'


async def main():
    install_patches()
    _SB.fail_substr = None

    # --- _extract_json (real) ------------------------------------------------
    print("_extract_json:")
    check("parses bare object", _extract_json('{"a": 1}') == {"a": 1})
    check("parses ```json fence", _extract_json('```json\n{"a": 2}\n```') == {"a": 2})
    check("parses prose-wrapped object",
          _extract_json('Sure, here you go: {"chart_type": "bar"} — enjoy!') == {"chart_type": "bar"})
    check("parses array", _extract_json('["Q1?", "Q2?"]') == ["Q1?", "Q2?"])
    check("garbage raises LLMResolveError",
          await expect_raises(LLMResolveError, _as_coro(_extract_json, "not json at all")))

    # --- explain_sql (#22 explain) ------------------------------------------
    print("explain_sql (#22 explain):")
    set_llm("This query totals revenue per region and groups the output by region.")
    text = await ai_service.explain_sql(GOOD_SQL, SCHEMA, {})
    check("returns prose", "revenue" in text.lower())
    check("SQL appears in the prompt", GOOD_SQL in _LLM.calls[-1][2])
    set_llm("")  # empty reply
    check("empty reply raises LLMResolveError",
          await expect_raises(LLMResolveError, ai_service.explain_sql(GOOD_SQL, SCHEMA, {})))

    # --- rewrite_sql fix (#22 fix): happy path ------------------------------
    print("rewrite_sql fix (#22):")
    _SB.fail_substr = None
    set_llm('{"sql": ' + _json_str(GOOD_SQL) + ', "explanation": "Added the GROUP BY."}')
    res = await ai_service.rewrite_sql("fix", "SELECT region, SUM(revenue) FROM sales", "some error", SCHEMA, {})
    check("fix returns validated SQL", res["sql"].startswith("SELECT"))
    check("fix retries_used == 0 on first success", res["retries_used"] == 0)
    check("fix carries explanation", "group by" in res["explanation"].lower())
    check("fix error text reached prompt", "some error" in _LLM.calls[0][2])

    # --- rewrite_sql fix: self-correct after a failed dry-run ----------------
    _SB.fail_substr = "bad_col"
    set_llm(
        '{"sql": "SELECT bad_col FROM sales", "explanation": "attempt 1"}',   # dry-run fails
        '{"sql": ' + _json_str(GOOD_SQL) + ', "explanation": "attempt 2"}',   # clean
    )
    res = await ai_service.rewrite_sql("fix", "SELECT x FROM sales", None, SCHEMA, {})
    check("self-corrects after dry-run failure (retries_used == 1)", res["retries_used"] == 1)
    check("final SQL is the clean one", "bad_col" not in res["sql"])

    # --- rewrite_sql: rejects a non-SELECT from the model (validator) --------
    _SB.fail_substr = None
    set_llm(
        '{"sql": "DROP TABLE sales", "explanation": "nope"}',                 # validator rejects
        '{"sql": ' + _json_str(GOOD_SQL) + ', "explanation": "ok now"}',
    )
    res = await ai_service.rewrite_sql("optimize", GOOD_SQL, None, SCHEMA, {})
    check("validator rejects a write, then self-corrects", res["retries_used"] == 1 and "DROP" not in res["sql"].upper())

    # --- rewrite_sql: exhausts attempts -> LLMResolveError -------------------
    set_llm(
        '{"sql": "DELETE FROM sales", "explanation": "x"}',
        "not even json",
        '{"sql": "UPDATE sales SET x=1", "explanation": "x"}',
    )
    check("exhausted attempts raise LLMResolveError",
          await expect_raises(LLMResolveError, ai_service.rewrite_sql("fix", "bad", "err", SCHEMA, {})))

    # --- suggest_questions (#26) --------------------------------------------
    print("suggest_questions (#26):")
    set_llm('["What is total revenue by region?", "Top 5 products by revenue?", "Top 5 products by revenue?", "Average revenue per product?"]')
    qs = await ai_service.suggest_questions(SCHEMA)
    check("dedups case-insensitively (3 unique from 4)", len(qs) == 3, f"got {len(qs)}")
    check("questions are non-empty strings", all(isinstance(q, str) and q for q in qs))
    set_llm('{"not": "a list"}')
    check("non-list raises LLMResolveError",
          await expect_raises(LLMResolveError, ai_service.suggest_questions(SCHEMA)))
    set_llm('[]')
    check("empty list raises LLMResolveError",
          await expect_raises(LLMResolveError, ai_service.suggest_questions(SCHEMA)))

    # --- narrate_dataset (#29) ----------------------------------------------
    print("narrate_dataset (#29):")
    set_llm("This dataset records sales transactions with a region, product and revenue per row.")
    story = await ai_service.narrate_dataset(SCHEMA)
    check("returns narrative prose", "sales" in story.lower())
    check("schema DDL reached the prompt", "CREATE TABLE sales" in _LLM.calls[-1][2])

    # --- recommend_chart (#30) ----------------------------------------------
    print("recommend_chart (#30):")
    set_llm('{"chart_type": "line", "reasoning": "It shows a trend over time.", "alternatives": ["area", "bar", "pie"]}')
    rec = await ai_service.recommend_chart("order_date", "DATE", "show the trend", SCHEMA)
    check("returns the recommended type", rec["chart_type"] == "line")
    check("alternatives filtered to supported set & capped at 2", len(rec["alternatives"]) == 2 and "line" not in rec["alternatives"])
    check("column + intent reached the prompt", "order_date" in _LLM.calls[-1][2] and "trend" in _LLM.calls[-1][2])
    set_llm('{"chart_type": "sankey", "reasoning": "x", "alternatives": ["treemap"]}')
    rec = await ai_service.recommend_chart("region", "VARCHAR", None, SCHEMA)
    check("out-of-set type falls back to bar", rec["chart_type"] == "bar")
    check("out-of-set alternatives dropped", rec["alternatives"] == [])
    set_llm('["not", "a", "dict"]')
    check("non-object raises LLMResolveError",
          await expect_raises(LLMResolveError, ai_service.recommend_chart("region", None, None, SCHEMA)))

    # --- explain_chart (#18) -------------------------------------------------
    print("explain_chart (#18):")
    set_llm("Revenue is concentrated in the North, which leads all regions by a wide margin.")
    spec = {
        "title": "Revenue by region", "chart_type": "bar", "dimension": "region",
        "measure": "revenue", "aggregation": "sum",
        "keys": ["North", "South", "East"], "values": [1750, 900, 400],
    }
    narr = await ai_service.explain_chart(spec)
    check("returns narrative", "north" in narr.lower())
    prompt = _LLM.calls[-1][2]
    check("data points reached the prompt", "North: 1750" in prompt and "aggregation: sum".lower() in prompt.lower())

    # --- resolve_sql history threading (#21) --------------------------------
    print("resolve_sql history (#21):")
    _SB.fail_substr = None
    set_llm(GOOD_SQL)
    history = [{"question": "total revenue by region", "sql": GOOD_SQL}]
    res = await ai_service.resolve_sql("now only the top 2", SCHEMA, {}, history=history)
    prompt = _LLM.calls[-1][2]
    check("resolve_sql returns validated SQL + retries_used", res["sql"].startswith("SELECT") and res["retries_used"] == 0)
    check("history marker present in prompt", "Earlier in this conversation" in prompt)
    check("prior question threaded into prompt", "total revenue by region" in prompt)
    check("follow-up question threaded into prompt", "now only the top 2" in prompt)
    # No-history path must NOT include the follow-up scaffolding.
    set_llm(GOOD_SQL)
    await ai_service.resolve_sql("total revenue by region", SCHEMA, {})
    check("no-history prompt omits the conversation block", "Earlier in this conversation" not in _LLM.calls[-1][2])

    # --- _ask_cache_hash collision-avoidance (router) ------------------------
    print("_ask_cache_hash (#21 cache):")
    q = "total revenue by region"
    check("no-history hash == plain question hash (back-compat)",
          _ask_cache_hash(q, []) == _question_hash(q))

    class _T:
        def __init__(self, question, sql):
            self.question = question
            self.sql = sql

    h1 = _ask_cache_hash("now group by month", [_T(q, GOOD_SQL)])
    h2 = _ask_cache_hash("now group by month", [])
    check("history changes the hash (no collision with base question)", h1 != h2)
    h3 = _ask_cache_hash("now group by month", [_T(q, GOOD_SQL)])
    check("same (question, history) hashes stably", h1 == h3)

    # --- summary -------------------------------------------------------------
    print()
    ver = f" (v{redis_manager.server_version})" if getattr(redis_manager, "server_version", None) else ""
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}{ver}  "
          f"[not exercised: these tests mock LLM + DuckDB and are cache-independent]")
    print(f"CHECKS: {PASS} passed, {FAIL} failed")
    print("RESULT: ALL CHECKS PASSED" if FAIL == 0 else f"RESULT: {FAIL} CHECK(S) FAILED")
    sys.exit(1 if FAIL else 0)


def _as_coro(fn, *args):
    """Wrap a sync call that may raise into an awaitable, for expect_raises."""
    async def _c():
        return fn(*args)
    return _c()


def _json_str(s: str) -> str:
    """Encode a Python string as a JSON string literal (quotes + escaping) so it can
    be embedded inside a hand-built JSON response fixture."""
    import json
    return json.dumps(s)


if __name__ == "__main__":
    asyncio.run(main())
