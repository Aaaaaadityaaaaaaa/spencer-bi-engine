"""Proof for the S-2 data-loss guards (TASK-029):

  (a) RedisManager fails HARD in production instead of silently using the empty
      in-memory fakeredis (which would make the sweeper think every session is dead).
  (b) cleanup_service.sweep() refuses to reap when the store is untrusted in prod,
      so a boot on the fallback store deletes NOTHING.
  (c) dev behaviour is unchanged: unreachable Redis still falls back to fakeredis.

Run:  python backend/test_redis_failhard.py   (exit 0 = all guards hold)
"""
import asyncio
import os
import shutil
import tempfile

import config
from services.redis_manager import RedisManager, redis_manager
from services import cleanup_service

# An almost-certainly-closed localhost port so the connect fails fast (1s timeout).
CLOSED_PORT = 6390


def test_failhard_prod() -> bool:
    """(a) prod + unreachable Redis -> RuntimeError (no silent fallback)."""
    orig = config.IS_PRODUCTION
    try:
        config.IS_PRODUCTION = True
        try:
            RedisManager(host="127.0.0.1", port=CLOSED_PORT)
        except RuntimeError as exc:
            return "production" in str(exc).lower()
        return False  # should have raised
    finally:
        config.IS_PRODUCTION = orig


def test_fallback_dev() -> bool:
    """(c) dev + unreachable Redis -> fakeredis fallback (unchanged behaviour)."""
    orig = config.IS_PRODUCTION
    try:
        config.IS_PRODUCTION = False
        rm = RedisManager(host="127.0.0.1", port=CLOSED_PORT)
        return rm.backend == "fakeredis"
    finally:
        config.IS_PRODUCTION = orig


async def _sweep_guard() -> bool:
    """(b) prod + fakeredis backend -> sweep is a no-op and deletes nothing.

    We build a temp uploads dir with one 'dead-looking' session dir (old mtime,
    no liveness marker). Without the guard the sweep would reap it; with the
    guard it must early-return and leave the dir untouched."""
    tmp = tempfile.mkdtemp(prefix="spencer_sweep_test_")
    victim = os.path.join(tmp, "dead-session-uuid")
    os.makedirs(victim)
    os.utime(victim, (1, 1))  # epoch 1970 -> older than any grace window

    orig_env = config.IS_PRODUCTION
    orig_uploads = config.UPLOADS_DIR
    orig_backend = redis_manager.backend
    try:
        config.IS_PRODUCTION = True
        config.UPLOADS_DIR = tmp             # defence: if the guard fails, it hits tmp, not real uploads/
        redis_manager.backend = "fakeredis"  # simulate the silent-fallback state
        result = await cleanup_service.sweep()
        return result["sessions_reaped"] == 0 and os.path.isdir(victim)
    finally:
        config.IS_PRODUCTION = orig_env
        config.UPLOADS_DIR = orig_uploads
        redis_manager.backend = orig_backend
        shutil.rmtree(tmp, ignore_errors=True)


def run():
    results = {
        "(a) fail-hard in prod": test_failhard_prod(),
        "(c) fakeredis fallback in dev": test_fallback_dev(),
        "(b) sweep refuses on untrusted store": asyncio.run(_sweep_guard()),
    }
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    all_ok = all(results.values())
    print("PASS: all S-2 guards hold" if all_ok else "FAIL: an S-2 guard did not hold")
    return all_ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
