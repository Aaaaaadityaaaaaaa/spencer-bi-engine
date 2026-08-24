# TASK-024 — Quota-aware LLM API key pool (rotate on rate-limit)

**Status: AWAITING USER SIGN-OFF** (do not self-close)

## Objective
While testing Wave 4, a real Gemini call died with `litellm.RateLimitError … 429 … Quota exceeded …
limit: 20 … GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Root cause: the free tier is **20
requests/DAY/model** and every LLM call in the app funnels through a single env key — one key, one
daily bucket, hard stop when spent.

**Goal (user's words):** *"create an api key pool where we have multiple api keys and check if there
is a rate limit / quota left before using them."* Hold several keys, route each call to a key with
headroom, and transparently fail over when one is exhausted — turning a hard 429 into a silent
rotation, surfacing an error only when **every** key is spent.

**Honest constraint that drives the design:** Gemini exposes **no** "remaining quota" endpoint — you
cannot literally pre-check quota. So "check before use" is approximated by two mechanisms:
- **Reactive (primary):** on a 429, park the key in a Redis cooldown and retry the next healthy key.
  A **per-DAY** quota benches it for a long window (`LLM_DAILY_COOLDOWN_SECONDS`, ~6h → self-heals
  across the provider's midnight reset); a **per-minute** limit uses the short parsed `retryDelay`.
- **Proactive (secondary, opt-in):** a Redis per-key **daily success counter**; a key already at the
  soft cap is skipped without a call. Set the cap to `20` to mirror the Gemini free tier.

## What changed
### Backend (new)
- **`backend/services/llm_key_pool.py`** — the pool. Sync, Redis-backed, mirrors the codebase's
  sync-Redis-in-async-handler convention.
  - `__init__` parses env **once**, per provider merging the plural list with the singular var
    (`GEMINI_API_KEYS`+`GEMINI_API_KEY`; `ANTHROPIC_API_KEYS`+`ANTHROPIC_API_KEY`), split on `,`,
    stripped, blanks dropped, **deduped preserving order** → `{provider: [(keyid, key), …]}`.
  - `_keyid(key)` = `sha256(key)[:12]` (Redis identity — **raw key never stored**); `_mask(key)` =
    `AIza...wxyz` (logs only, ASCII ellipsis for a clean Windows console line).
  - `acquire(provider)` — round-robin, returning the first key **not** in cooldown
    (`llmkey:cooldown:{keyid}`) **and** under the soft cap (`llmkey:calls:{keyid}:{yyyymmdd}` when
    the cap > 0); `None` when all keys are cooling/capped.
  - `record_success` (`INCR` + `EXPIRE` ~2d) / `record_rate_limited` (`SETEX` cooldown). All state in
    Redis namespace `llmkey:*` → async- and worker-safe; degrades onto fakeredis when Redis is down.
- **`backend/test_llm_key_pool.py`** — hermetic proof (fakeredis + monkeypatched litellm), **23/23 green**.

### Backend (edits)
- **`backend/services/ai_service.py`** —
  - New **`LLMRateLimitError(LLMAPIError)`** (`code="llm_rate_limited"`, `retry_after`). A **subclass**,
    so every pre-existing `except LLMAPIError` still degrades safely to 502; only `ai.py` upgrades to 429.
  - `_resolve_model` now also detects the **plural** vars (`…_API_KEYS`) for provider selection.
  - **`_call_llm` rewritten** into a rotation loop: `provider = model.split("/")[0]`. **No pool →** one
    call with `api_key=None` (**byte-identical to before**, incl. 502 on failure). **Pool present →** up
    to `size(provider)` attempts: `acquire()` → `_one_call(api_key=key)`; a 429 → `record_rate_limited`
    (long bench if per-DAY, else `retryDelay`) + rotate; success → `record_success` + return; a **non-429**
    error bubbles as `LLMAPIError` immediately (a transport blip never burns the pool). Exhausted →
    `LLMRateLimitError(retry_after=soonest)`. Rotations logged with `_mask` only.
- **`backend/routers/ai.py`** — `LLMRateLimitError` import; a **429 (+`Retry-After`)** branch in `_llm_http`
  (before the `LLMAPIError` branch — subclass ordering) and in `ask_question` (before `except LLMAPIError`;
  a rate-limit is **not** fail-cached). The 5 Wave-4 routes inherit 429 automatically via `_llm_http`.
- **`backend/config.py`** — three non-secret knobs (below). **`.env.example`** — documents
  `GEMINI_API_KEYS`/`ANTHROPIC_API_KEYS` (secret, gitignored) + the three knobs.

### Frontend
None. (No frontend change; strict build untouched.)

## Config
| Env var | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEYS` / `ANTHROPIC_API_KEYS` | — | Comma-separated key pool (**secret**; merged with the singular var, deduped, order preserved). Singular still works as a 1-key pool. |
| `SPENCER_LLM_DAILY_LIMIT_PER_KEY` | `0` (off) | Proactive per-key/UTC-day success cap; a key at the cap is skipped without a call. Set `20` to mirror the Gemini free tier. |
| `SPENCER_LLM_KEY_COOLDOWN_SECONDS` | `60` | Reactive bench for a per-minute 429 that carries no `retryDelay`. |
| `SPENCER_LLM_DAILY_COOLDOWN_SECONDS` | `21600` (6h) | Reactive bench for a per-DAY quota; ~6h self-heals across the daily reset with no timezone math. |

## Security (AP-8)
- **Secrets stay secret.** Keys live only in gitignored `backend/.env` (never read/echoed/committed by me).
  Redis stores only `sha256(key)[:12]` keyids + counters/cooldowns — **never a raw key**. Logs show only
  `_mask` (`AIza...wxyz`). **No endpoint returns or reflects a key** (test [2] + design).
- **No new client-controlled surface.** Keys/knobs come only from server env; nothing key-related is
  accepted from a request. The per-call `api_key=` is server-selected, never client-supplied.
- **Fail-safe.** Pool absent/misparsed → today's single-env-key behavior (byte-identical). All keys spent →
  clean retryable **429 + `Retry-After`**, no stack leak. Rate-limits are **not** fail-cached.
- **Bounded work.** Rotation is capped at `size(provider)` attempts/request; each 429 benches a key so a
  storm can't spin. No new external calls beyond the same LLM endpoint.

## Acceptance criteria
1. ✅ `backend/test_llm_key_pool.py` **23/23 green**; no frontend change (strict build untouched).
2. ✅ **Parsing:** `GEMINI_API_KEYS="k1,k2, k3,k2"` + `GEMINI_API_KEY="k0"` → `[k1,k2,k3,k0]` (order kept,
   blank/dupe dropped, stripped); singular-alone → 1-key pool (test [1]).
3. ⏳ **Live intra-provider failover** — **pending the user's real keys** in `backend/.env` (see S-1). The
   *mechanics* are proven hermetically (test [7]): a per-DAY 429 on k1 benches it with the **long** cooldown
   and the same call transparently succeeds on **k2**, with a success counted on k2.
4. ✅ **All-exhausted → 429:** proven at the `_call_llm` layer (test [8]: `LLMRateLimitError`, `retry_after=33`);
   `ai.py` maps it to HTTP **429 + `Retry-After`** in both `_llm_http` and `ask_question` (code path in place;
   end-to-end HTTP capture rides the live step in #3).
5. ✅ **Proactive cap:** with cap `2`, a key is skipped after 2 successes; counter visible at
   `llmkey:calls:{keyid}:{today}` (test [6]).
6. ✅ **No-pool path unchanged:** single env key → one call with `api_key=None`; a **non-429** failure still
   maps to 502 and **does not** bench a key (test [9]).
7. ✅ **Secrets:** only keyids/masks appear in Redis + logs; `_mask` hides the middle; no endpoint returns a
   key (test [2] + design).
8. ✅ **Must-not-change** verified: `README.md`, `duckdb_manager.py`, `sql_validator.py` absent from any diff.
   `.ai/CURRENT_STATE.md`, `session.py`, `query.py`, `redis_manager.py` show a diff, but it is **pre-existing
   parallel TASK-013 work at session start — not mine** (I edited none of them).

## Verification (real output)
- **Unit (hermetic):** `cd backend && python test_llm_key_pool.py` → `RESULT: 23 passed, 0 failed`. Uses
  **fakeredis** + a monkeypatched `litellm.acompletion` (no network, no real keys, no running Redis). Run
  from a throwaway CWD so `duckdb.connect("spencer.db")` doesn't collide with the live backend's DB lock.
- **Byte-compile:** `py_compile` clean on all five edited/new backend files.
- **Live failover (pending user, no wasted quota):** put 2+ real Gemini keys in gitignored `backend/.env` as
  `GEMINI_API_KEYS=AIza...k1,AIza...k2` and restart backend (`uvicorn --workers 1`). Drive `/ask` until k1
  hits its daily 429 (or temporarily set a tiny `SPENCER_LLM_KEY_COOLDOWN_SECONDS` with one invalid key
  alongside a real one) and confirm the next call serves from k2; inspect Redis
  (`./tools/redis/redis-cli.exe -p 6380 KEYS 'llmkey:*'`) for `cooldown:*`/`calls:*` and the backend log's
  masked rotation line (**no raw key**). Then force all-benched and confirm a Wave-4 route + `/ask` return
  **429 + `Retry-After`** in the network trace.

## Definition of Done
Quota-aware key pool implemented at the single LLM chokepoint over the existing Redis substrate; a hard
per-day 429 becomes a silent intra-provider rotation, and all-spent becomes a clean retryable 429. Hermetic
proof green (23/23), byte-compile clean, must-not-change verified. Left in `tasks/active/` for the user's
single sign-off. **Not self-closed.** `README.md` / `.ai/CURRENT_STATE.md` / real `backend/.env` untouched.

## Self-review (severity-graded)
**Critical / High: none.**

- **S-1 (Medium — needs you).** *Live real-key failover (AC #3) is not yet proven.* Every mechanism is proven
  hermetically, but the actual "429 on real key k1 → real key k2 serves it" round-trip can't be demonstrated
  until **2+ real `AIzaSy…` Gemini keys** are in gitignored `backend/.env` as `GEMINI_API_KEYS=...` (I don't
  handle the raw values). The 6 tokens pasted earlier were **not added** — they begin `AQ.Ab8RN6…`, not the
  `AIzaSy…`/39-char Gemini API-key format; adding them would fail auth and add zero quota (see S-7). Grab real
  keys from aistudio.google.com/apikey, drop them in, restart the backend, and I'll prove failover live.
- **S-2 (Low — by design).** *The proactive cap's day boundary is UTC; Gemini resets at Pacific midnight,* so
  the `…:{yyyymmdd}` counter can be ~7-8h out of phase with the real reset. That's exactly why the cap is a
  **soft, opt-in secondary** (default **off**) and the **reactive** ~6h per-DAY bench — which self-heals across
  the provider's own reset — is the real protection. At the cap it may slightly under-use a key near the
  boundary but never over-calls. Deliberate (avoids TZ/DST math).
- **S-3 (Low — by design).** *`record_success`/`record_rate_limited` are best-effort (swallow Redis errors).*
  On a Redis hiccup the counter under-counts (soft cap relaxes) or a bench doesn't persist — the pool degrades
  toward **availability** (keeps trying keys) rather than blocking. With the fakeredis fallback this is near-
  impossible in practice; flagged for honesty.
- **S-4 (Low — moot today).** *The round-robin cursor is per-process, in-memory.* Under multiple uvicorn
  workers each worker round-robins from its own offset, so the *starting* key isn't globally even — but
  cooldowns/counters are in **Redis** (shared), so correctness (skip benched/capped keys) holds across workers.
  The app runs `--workers 1` (single-writer, ADR), so this is a future scale-out note only.
- **S-5 (Low).** *429 detection + per-DAY classification are heuristic.* `_is_rate_limit` covers typed
  `RateLimitError` + `status_code==429` + a name match; `is_daily` matches substrings
  (`perday`/`per_day`/`/day`/`free_tier_requests`). If a provider reworded its 429, a per-DAY quota could be
  read as per-minute (a short bench instead of ~6h) — still safe, just re-benched on the next attempt. The
  `retryDelay` regex grabs the first number after the marker, so both `retryDelay: '33s'` and
  `retry_delay { seconds: 33 }` parse.
- **S-6 (Info).** *Anthropic pooling ships but wasn't exercised live* (no multiple Claude keys here); the code
  path is provider-symmetric. Cross-provider fallback (Gemini→Anthropic) is explicitly **out of scope** — a
  documented follow-on.
- **S-7 (Info — security).** *If the 6 tokens pasted in chat are live credentials of any system, revoke them* —
  they were shared in the conversation. They were not added to the pool.
- **S-8 (Info — pre-existing, out of scope).** *`_classify_db_error` is called at `ai_service.py:405` but never
  defined* (its body is orphaned inside `_extract_json`, ~241-253) — a latent `NameError` in `resolve_sql`'s
  dry-run retry path, unrelated to this task. Recommend a separate one-line fix (hoist the function definition).
