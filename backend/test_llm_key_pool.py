"""TASK-024 proof: quota-aware LLM API key pool (rotate on rate-limit).

Unit-level and HERMETIC -- uses fakeredis (NOT the shared real Redis) and a
monkeypatched ``litellm.acompletion``, so it needs no network, no real API keys, and
no running Redis. Standalone + idempotent (AP-7): every subtest builds a fresh pool
over a fresh fakeredis, so re-running yields identical results.

Covers each acceptance criterion with printed, assertable output:
  1. parsing: plural+singular merge, comma-split, strip, blank-drop, dedupe, order
  2. _keyid is stable + 12 hex chars; _mask hides the middle of the key (secrets)
  3. round-robin spread across successive acquire()
  4. record_rate_limited -> acquire skips the benched key -> returns the next healthy one
  5. every key benched -> acquire returns None (caller then surfaces a clean 429)
  6. proactive daily cap (limit=2): a key is skipped after 2 recorded successes
  7. _call_llm rotation: a per-DAY 429 on k1 benches it with the LONG cooldown and the
     same call transparently succeeds on k2, with a success counted on k2
  8. all-429 -> LLMRateLimitError carrying retry_after (the soonest hint)
  9. retryDelay "33s" parsed; per-DAY marker -> daily cooldown; a NON-429 error bubbles
     as LLMAPIError WITHOUT benching any key
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakeredis

import config
import services.ai_service as ai_mod
import services.llm_key_pool as pool_mod
from services.ai_service import LLMAPIError, LLMRateLimitError, _rate_limit_signal
from services.llm_key_pool import LLMKeyPool

_ENV_VARS = ("GEMINI_API_KEYS", "GEMINI_API_KEY", "ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")


class _FakeRM:
    """Minimal redis_manager stand-in: just the ``.client`` attribute the pool uses."""

    def __init__(self):
        self.client = fakeredis.FakeStrictRedis(decode_responses=True)


def _pool(gemini_keys=None, singular=None) -> LLMKeyPool:
    """Build a fresh pool over a fresh fakeredis with a clean, explicit env."""
    for var in _ENV_VARS:
        os.environ.pop(var, None)
    if gemini_keys is not None:
        os.environ["GEMINI_API_KEYS"] = gemini_keys
    if singular is not None:
        os.environ["GEMINI_API_KEY"] = singular
    return LLMKeyPool(_FakeRM())


def _resp(content="SELECT 1"):
    """A minimal object shaped like a LiteLLM completion response."""
    msg = type("_Msg", (), {"content": content})()
    choice = type("_Choice", (), {"message": msg})()
    return type("_Resp", (), {"choices": [choice]})()


class _FakeRateLimitError(Exception):
    """Stands in for litellm.RateLimitError -- status_code 429 makes _is_rate_limit fire."""

    status_code = 429


_passed = 0
_failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}")


def main():
    print("=" * 72)
    print("TASK-024 -- LLM API key pool (backend: fakeredis, litellm monkeypatched)")
    print("=" * 72)

    # 1. parsing -----------------------------------------------------------
    print("\n[1] Env parsing: merge / split / strip / dedupe / order")
    p = _pool(gemini_keys="k1,k2, k3,k2", singular="k0")
    keys = [k for _, k in p._keys.get("gemini", [])]
    check("plural+singular merge, dedupe, order preserved -> [k1,k2,k3,k0]",
          keys == ["k1", "k2", "k3", "k0"])
    check("size('gemini') == 4", p.size("gemini") == 4)
    check("has_keys: gemini True, anthropic False",
          p.has_keys("gemini") and not p.has_keys("anthropic"))
    p2 = _pool(singular="solo")
    check("singular var alone still forms a 1-key pool", p2.size("gemini") == 1)

    # 2. keyid / mask ------------------------------------------------------
    print("\n[2] _keyid stable + _mask hides the key (secrets)")
    secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
    kid1, kid2 = LLMKeyPool._keyid(secret), LLMKeyPool._keyid(secret)
    check("_keyid deterministic", kid1 == kid2)
    check("_keyid is 12 hex chars", len(kid1) == 12 and all(c in "0123456789abcdef" for c in kid1))
    masked = LLMKeyPool._mask(secret)
    check("_mask keeps only first4+last4, drops the middle",
          masked.startswith("AIza") and masked.endswith("3456")
          and "ABCDEFGHIJKLMNOP" not in masked and secret not in masked)

    # 3. round-robin -------------------------------------------------------
    print("\n[3] Round-robin spread")
    p = _pool(gemini_keys="k1,k2,k3")
    seq = [p.acquire("gemini")[1] for _ in range(4)]
    check("acquire spreads k1,k2,k3 then wraps to k1", seq == ["k1", "k2", "k3", "k1"])

    # 4. bench -> skip -----------------------------------------------------
    print("\n[4] record_rate_limited benches a key, acquire rotates past it")
    p = _pool(gemini_keys="k1,k2,k3")
    kid_k1 = p._keys["gemini"][0][0]
    p.record_rate_limited("gemini", kid_k1, 300)
    got = [p.acquire("gemini")[1] for _ in range(2)]
    check("benched k1 skipped -> k2 then k3", got == ["k2", "k3"])

    # 5. all benched -> None ----------------------------------------------
    print("\n[5] All keys benched -> acquire None")
    p = _pool(gemini_keys="k1,k2")
    for kid, _ in p._keys["gemini"]:
        p.record_rate_limited("gemini", kid, 300)
    check("acquire returns None when every key is cooling down", p.acquire("gemini") is None)

    # 6. proactive daily cap ----------------------------------------------
    print("\n[6] Proactive daily soft cap (limit=2)")
    p = _pool(gemini_keys="k1")
    kid = p._keys["gemini"][0][0]
    orig_cap = pool_mod.LLM_DAILY_LIMIT_PER_KEY
    pool_mod.LLM_DAILY_LIMIT_PER_KEY = 2
    try:
        ok1 = p.acquire("gemini") is not None
        p.record_success("gemini", kid)
        ok2 = p.acquire("gemini") is not None
        p.record_success("gemini", kid)
        blocked = p.acquire("gemini") is None
        check("acquire ok while used < cap, None once used >= cap", ok1 and ok2 and blocked)
        check("counter visible at llmkey:calls:{keyid}:{today}",
              p._rm.client.get(f"llmkey:calls:{kid}:{p._today()}") == "2")
    finally:
        pool_mod.LLM_DAILY_LIMIT_PER_KEY = orig_cap

    # 7-9. _call_llm rotation (needs litellm) ------------------------------
    print("\n[7-9] _call_llm rotation via monkeypatched litellm.acompletion")
    if ai_mod.litellm is None:
        print("  [SKIP] litellm not installed -- rotation tests skipped (unit env only)")
    else:
        real_acompletion = ai_mod.litellm.acompletion
        orig_pool = ai_mod.llm_key_pool
        try:
            # 7: per-DAY 429 on k1 -> long bench + success on k2
            tp = _pool(gemini_keys="k1,k2")
            ai_mod.llm_key_pool = tp
            seen = []

            async def fake_daily(**kw):
                seen.append(kw.get("api_key"))
                if kw.get("api_key") == "k1":
                    raise _FakeRateLimitError(
                        "litellm.RateLimitError: Quota exceeded for metric ... "
                        "GenerateRequestsPerDayPerProjectPerModel-FreeTier ... retryDelay: '30s'"
                    )
                return _resp("SELECT 1")

            ai_mod.litellm.acompletion = fake_daily
            out = asyncio.run(ai_mod.ai_service._call_llm("gemini/gemini-2.5-flash", "s", "u"))
            check("rotation returns content from k2", out == "SELECT 1")
            check("rotation tried k1 then k2 in order", seen == ["k1", "k2"])
            kid_a = tp._keys["gemini"][0][0]
            kid_b = tp._keys["gemini"][1][0]
            ttl = tp._rm.client.ttl(f"llmkey:cooldown:{kid_a}")
            check("k1 benched with the per-DAY (long) cooldown",
                  ttl > config.LLM_KEY_COOLDOWN_SECONDS)
            check("success recorded on k2",
                  tp._rm.client.get(f"llmkey:calls:{kid_b}:{tp._today()}") == "1")

            # 8: all-429 -> LLMRateLimitError with retry_after
            tp2 = _pool(gemini_keys="k1,k2")
            ai_mod.llm_key_pool = tp2

            async def fake_all(**kw):
                raise _FakeRateLimitError("rate limit exceeded; retryDelay: '33s'")  # per-minute

            ai_mod.litellm.acompletion = fake_all
            err = None
            try:
                asyncio.run(ai_mod.ai_service._call_llm("gemini/gemini-2.5-flash", "s", "u"))
            except Exception as e:  # noqa: BLE001 - capturing to assert type
                err = e
            check("all keys 429 -> LLMRateLimitError", isinstance(err, LLMRateLimitError))
            check("LLMRateLimitError.retry_after == 33 (soonest)",
                  getattr(err, "retry_after", None) == 33)

            # 9: non-429 bubbles as LLMAPIError WITHOUT benching
            tp3 = _pool(gemini_keys="k1,k2")
            ai_mod.llm_key_pool = tp3

            async def fake_boom(**kw):
                raise ValueError("connection reset by peer")

            ai_mod.litellm.acompletion = fake_boom
            err = None
            try:
                asyncio.run(ai_mod.ai_service._call_llm("gemini/gemini-2.5-flash", "s", "u"))
            except Exception as e:  # noqa: BLE001
                err = e
            check("non-429 -> LLMAPIError (not LLMRateLimitError)",
                  isinstance(err, LLMAPIError) and not isinstance(err, LLMRateLimitError))
            kid_boom = tp3._keys["gemini"][0][0]
            check("non-429 does NOT bench the key",
                  tp3._rm.client.ttl(f"llmkey:cooldown:{kid_boom}") in (-2, -1))
        finally:
            ai_mod.litellm.acompletion = real_acompletion
            ai_mod.llm_key_pool = orig_pool

    # 9b: classifier unit checks (no litellm needed) -----------------------
    print("\n[9b] 429 classification: retryDelay parse + per-DAY marker")
    sig = _rate_limit_signal(_FakeRateLimitError("blah retryDelay: '33s' blah"))
    check("retryDelay '33s' parsed to 33", sig.retry_after == 33)
    check("per-minute (no daily marker) cooldown == retry_after", sig.cooldown_s == 33 and not sig.is_daily)
    sig_d = _rate_limit_signal(_FakeRateLimitError("PerDay quota exhausted, retryDelay: '30s'"))
    check("per-DAY marker -> LONG daily cooldown",
          sig_d.is_daily and sig_d.cooldown_s == config.LLM_DAILY_COOLDOWN_SECONDS)

    # clean up env we set
    for var in _ENV_VARS:
        os.environ.pop(var, None)

    print("\n" + "=" * 72)
    print(f"RESULT: {_passed} passed, {_failed} failed")
    print("=" * 72)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
