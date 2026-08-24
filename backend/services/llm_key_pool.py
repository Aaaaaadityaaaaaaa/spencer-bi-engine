"""Quota-aware LLM API key pool (TASK-024).

Every LLM request in the app funnels through ``ai_service._call_llm``, which used to
read a single key from the environment via LiteLLM. On the Gemini free tier that one
key is capped at **20 requests/day/model**, so a busy session hits a hard 429 with no
recourse. This pool holds MULTIPLE keys per provider and rotates across them:

* **REACTIVE (primary):** on a 429 the offending key is parked in a Redis cooldown and
  the next healthy key serves the retry. A per-DAY quota benches the key for a long
  window (``LLM_DAILY_COOLDOWN_SECONDS``); a per-minute limit uses the short retryDelay.
* **PROACTIVE (secondary, opt-in):** a per-key per-day success counter; once a key has
  reached ``LLM_DAILY_LIMIT_PER_KEY`` it is skipped without even being tried.

Design notes:

* **Secrets never touch Redis or logs.** Redis is keyed by ``sha256(key)[:12]`` (a
  "keyid"); logs show only ``_mask(key)``. The raw key lives only in this process's
  memory, read once from the environment at construction.
* **All rotation state lives in Redis** (namespace ``llmkey:*``) so it is shared across
  async tasks and uvicorn workers, and degrades safely onto ``redis_manager``'s
  in-process fakeredis when Redis is down.
* **Methods are synchronous** (they do only fast Redis GET/SET, no network I/O),
  mirroring the codebase's "sync Redis inside an async handler" convention. Each runs
  to completion without awaiting, so the round-robin cursor needs no lock under asyncio.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from config import (
    LLM_DAILY_COOLDOWN_SECONDS,  # noqa: F401  (referenced by ai_service, kept discoverable here)
    LLM_DAILY_LIMIT_PER_KEY,
    LLM_KEY_COOLDOWN_SECONDS,  # noqa: F401  (referenced by ai_service)
)
from services.redis_manager import redis_manager

logger = logging.getLogger("spencer.ai")

# Redis key namespaces. Only keyids (sha256 prefixes) ever appear here -- never a raw key.
_COOLDOWN_KEY = "llmkey:cooldown:{keyid}"
_CALLS_KEY = "llmkey:calls:{keyid}:{day}"

# The per-day success counter outlives a single UTC day so a read near midnight can't
# under-count; two days is ample and self-expires (keeps Redis tidy without a sweep).
_CALLS_TTL_SECONDS = 2 * 24 * 3600

# Providers we pool, mapped to (plural_env_var, singular_env_var). The singular vars are
# the pre-existing single-key config, still honoured as a one-key pool.
_PROVIDER_ENV: Dict[str, Tuple[str, str]] = {
    "gemini": ("GEMINI_API_KEYS", "GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"),
}


class LLMKeyPool:
    """Holds N keys per provider and hands out one with headroom, rotating on 429.

    Constructed with a ``redis_manager``-like object exposing a ``.client`` attribute
    (the real singleton in production, a fakeredis-backed stub in tests). Env is parsed
    exactly once, at construction.
    """

    def __init__(self, redis_manager) -> None:
        self._rm = redis_manager
        self._keys: Dict[str, List[Tuple[str, str]]] = {}
        self._cursor: Dict[str, int] = {}
        for provider, (plural_var, singular_var) in _PROVIDER_ENV.items():
            keys = self._parse_keys(plural_var, singular_var)
            if keys:
                self._keys[provider] = keys
                self._cursor[provider] = 0
                logger.info(
                    "llm_key_pool: %s pool has %d key(s): %s",
                    provider,
                    len(keys),
                    ", ".join(self._mask(k) for _, k in keys),
                )

    # --- parsing / identity -------------------------------------------------

    @staticmethod
    def _keyid(key: str) -> str:
        """Stable, non-reversible Redis identity for a key (never the key itself)."""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _mask(key: str) -> str:
        """Short masked form for logs: first 4 + last 4 chars, never the middle. ASCII
        ellipsis so it renders cleanly in a Windows console (cp1252) log line too."""
        if len(key) <= 8:
            return "..."  # too short to reveal any of it
        return f"{key[:4]}...{key[-4:]}"

    def _parse_keys(self, plural_var: str, singular_var: str) -> List[Tuple[str, str]]:
        """Merge the comma-list plural var with the singular var into an ordered,
        de-duplicated list of ``(keyid, key)``. Blanks dropped; first occurrence wins;
        order (plural entries first, then the singular) is preserved."""
        raw: List[str] = []
        raw.extend((os.getenv(plural_var) or "").split(","))
        raw.append(os.getenv(singular_var) or "")
        seen: set = set()
        out: List[Tuple[str, str]] = []
        for item in raw:
            k = item.strip()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append((self._keyid(k), k))
        return out

    # --- capacity -----------------------------------------------------------

    def has_keys(self, provider: str) -> bool:
        return bool(self._keys.get(provider))

    def size(self, provider: str) -> int:
        return len(self._keys.get(provider) or [])

    # --- rotation -----------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def acquire(self, provider: str) -> Optional[Tuple[str, str]]:
        """Return the next ``(keyid, key)`` that is neither in cooldown nor over the
        daily soft cap, advancing the round-robin cursor past it. ``None`` when every
        key is cooling down or capped (the caller then surfaces a clean 429)."""
        keys = self._keys.get(provider) or []
        n = len(keys)
        if n == 0:
            return None
        client = self._rm.client
        cap = LLM_DAILY_LIMIT_PER_KEY
        day = self._today()
        start = self._cursor.get(provider, 0)
        for i in range(n):
            idx = (start + i) % n
            keyid, key = keys[idx]
            if client.get(_COOLDOWN_KEY.format(keyid=keyid)):
                continue  # benched by a recent 429
            if cap > 0:
                used = int(client.get(_CALLS_KEY.format(keyid=keyid, day=day)) or 0)
                if used >= cap:
                    continue  # proactively over the per-day soft cap
            self._cursor[provider] = (idx + 1) % n
            return keyid, key
        return None

    def record_success(self, provider: str, keyid: str) -> None:
        """Count one successful call against the key's per-day bucket (for the soft cap).
        Best-effort: a Redis hiccup here just means the proactive cap under-counts, and
        the reactive 429 path still protects the pool."""
        try:
            client = self._rm.client
            name = _CALLS_KEY.format(keyid=keyid, day=self._today())
            client.incr(name)
            client.expire(name, _CALLS_TTL_SECONDS)
        except Exception:  # pragma: no cover - counter is best-effort telemetry
            logger.debug("llm_key_pool: could not record success for %s", keyid)

    def record_rate_limited(self, provider: str, keyid: str, cooldown_s: int) -> None:
        """Bench a rate-limited key for ``cooldown_s`` seconds so ``acquire`` skips it."""
        try:
            self._rm.client.setex(
                _COOLDOWN_KEY.format(keyid=keyid), max(1, int(cooldown_s)), "1"
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("llm_key_pool: could not bench %s", keyid)


# Module-level singleton, parsed from the process environment (main.py loads backend/.env
# before this import runs). Tests construct their own LLMKeyPool with an explicit stub.
llm_key_pool = LLMKeyPool(redis_manager)
