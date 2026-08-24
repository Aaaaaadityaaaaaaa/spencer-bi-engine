"""TASK-013 cleanup-sweep proof.

Idempotent (AP-7): drops its own tables / rmtrees its own dirs / purges its own
Redis keys up front AND at the end, and runs the sweep twice to show stability.
Prints the Redis backend (AP-9) -- a real `redis` backend is required for this
to certify anything; a `fakeredis` line means the run is informational only.

Fixtures (fixed uuids so teardown is deterministic):
  DEAD  -> dir (old mtime) + table + schema key, NO liveness marker  => reaped
  LIVE  -> dir (old mtime) + table + schema key + fresh marker       => survives
  GRACE -> dir (FRESH mtime) + table, no marker                      => protected
           by the grace window (an in-flight upload must not be reaped mid-upload)

Run twice back-to-back to demonstrate idempotency:
    python test_cleanup.py && python test_cleanup.py
"""
import asyncio
import os
import shutil
import time

import config
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager
from services import cleanup_service

DEAD = "dead1111-1111-1111-1111-111111111111"
LIVE = "live2222-2222-2222-2222-222222222222"
GRACE = "grace333-3333-3333-3333-333333333333"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tname(session_uuid: str) -> str:
    return f"t_{session_uuid.replace('-', '_')}_probe"


def _dir(session_uuid: str) -> str:
    return os.path.join(config.UPLOADS_DIR, session_uuid)


async def _make_table(session_uuid: str) -> str:
    t = _tname(session_uuid)
    await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_q(t)}")
    await db_manager.run_readwrite(f"CREATE TABLE {_q(t)} AS SELECT 1 AS id")
    return t


def _make_dir(session_uuid: str, *, fresh: bool) -> None:
    d = _dir(session_uuid)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "probe.csv"), "w") as f:
        f.write("id\n1\n")
    if not fresh:
        # Backdate the DIRECTORY mtime past the grace window (must happen AFTER
        # writing the file, which itself bumps the dir mtime).
        old = time.time() - (config.SWEEP_GRACE_SECONDS + 120)
        os.utime(d, (old, old))


async def _table_exists(t: str) -> bool:
    rows = await db_manager.run_readwrite(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", (t,)
    )
    return rows[0][0] > 0


async def _teardown(*uuids: str) -> None:
    for u in uuids:
        await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_q(_tname(u))}")
        shutil.rmtree(_dir(u), ignore_errors=True)
        redis_manager.purge_session(u)


async def test_cleanup():
    print(f"REDIS BACKEND IN USE: {redis_manager.backend}")
    if redis_manager.backend != "redis":
        print("WARNING: not a real Redis -- per AP-9 this run does NOT certify the cache path.")

    # --- idempotent up-front teardown of THIS test's fixtures (AP-7) ---
    await _teardown(DEAD, LIVE, GRACE)

    # --- fixtures ---
    t_dead = await _make_table(DEAD)
    _make_dir(DEAD, fresh=False)
    redis_manager.set_json(f"schema:{DEAD}", {"_": "probe"})  # no liveness marker

    t_live = await _make_table(LIVE)
    _make_dir(LIVE, fresh=False)
    redis_manager.set_json(f"schema:{LIVE}", {"_": "probe"})
    redis_manager.touch_session(LIVE, config.SESSION_TTL_SECONDS)

    t_grace = await _make_table(GRACE)
    _make_dir(GRACE, fresh=True)  # within grace window

    # preconditions
    assert await _table_exists(t_dead) and await _table_exists(t_live) and await _table_exists(t_grace)
    assert redis_manager.session_alive(LIVE)
    assert not redis_manager.session_alive(DEAD)

    # --- sweep #1 ---
    r1 = await cleanup_service.sweep()
    print("sweep #1:", r1)

    checks = [
        ("DEAD table dropped", not await _table_exists(t_dead)),
        ("DEAD dir removed", not os.path.isdir(_dir(DEAD))),
        ("DEAD schema key purged", redis_manager.get_json(f"schema:{DEAD}") is None),
        ("LIVE table kept", await _table_exists(t_live)),
        ("LIVE dir kept", os.path.isdir(_dir(LIVE))),
        ("LIVE marker kept", redis_manager.session_alive(LIVE)),
        ("LIVE schema key kept", redis_manager.get_json(f"schema:{LIVE}") is not None),
        ("GRACE table kept (within grace)", await _table_exists(t_grace)),
        ("GRACE dir kept (within grace)", os.path.isdir(_dir(GRACE))),
        ("sweep reaped >=1 session", r1["sessions_reaped"] >= 1),
    ]

    # --- sweep #2 (idempotency) ---
    r2 = await cleanup_service.sweep()
    print("sweep #2:", r2)
    checks += [
        ("DEAD still gone after re-sweep", not await _table_exists(t_dead) and not os.path.isdir(_dir(DEAD))),
        ("LIVE still intact after re-sweep", await _table_exists(t_live) and redis_manager.session_alive(LIVE)),
        ("GRACE still intact after re-sweep", await _table_exists(t_grace) and os.path.isdir(_dir(GRACE))),
    ]

    passed = sum(1 for _, ok in checks if ok)
    for label, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}: {label}")
    print(f"\n{passed}/{len(checks)} assertions passed  (redis backend: {redis_manager.backend})")

    # --- end teardown: sweep intentionally KEEPS live+grace, so clean them here ---
    await _teardown(LIVE, GRACE)

    if passed != len(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(test_cleanup())
