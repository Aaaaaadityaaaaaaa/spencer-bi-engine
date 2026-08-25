"""Cleanup sweep (TASK-013).

Reclaims dead-session storage on a single long-running VM: DuckDB tables,
`uploads/{uuid}/` dirs, and Redis keys. A session is "dead" once its
`session:{uuid}` liveness marker (sliding TTL) has expired. Both the periodic
background loop and the manual `POST /admin/sweep` call `sweep()`.

Security (AP-8 / ADR-012): reclamation runs on ``run_readwrite`` -- the path
with *no* rollback -- so a filesystem-derived uuid is **never** interpolated
into SQL. We snapshot DuckDB's own catalog, filter table names in Python by the
session's identifier prefix, and only ever ``DROP`` catalog-sourced,
quote-escaped identifiers.

Everything routes through the existing ``run_readwrite`` wrapper; the frozen
``duckdb_manager`` is untouched.
"""
import asyncio
import logging
import os
import shutil
import time

import config
from services.duckdb_manager import db_manager
from services.redis_manager import redis_manager

logger = logging.getLogger("spencer.cleanup")

# Mirrors the frozen duckdb_manager's hardcoded db_path -- used only to report
# the on-disk size of the database file in storage_report().
DUCKDB_PATH = "spencer.db"


def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier, escaping embedded quotes. Names passed
    here come from DuckDB's own catalog, never from user input, but we quote
    defensively so an odd catalog name can never break out."""
    return '"' + name.replace('"', '""') + '"'


def _dir_size(path: str) -> int:
    """Total bytes of all files under `path` (best-effort; unreadable files are
    skipped rather than raising)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


async def sweep() -> dict:
    """Reclaim every dead session's tables + upload dir + Redis keys. Idempotent
    (``DROP ... IF EXISTS`` / ``rmtree(ignore_errors=True)`` / delete-if-present),
    so running it twice back-to-back is safe. Returns counts."""
    result = {
        "sessions_reaped": 0,
        "tables_dropped": 0,
        "dirs_removed": 0,
        "bytes_estimated": 0,
    }

    # S-2 (TASK-029): the sweep decides a session is dead from the ABSENCE of its
    # Redis liveness marker. If we are not on the real Redis in production, that
    # absence is meaningless (the in-memory fallback is simply empty), so reaping
    # would delete every tenant's data. Refuse to sweep on an untrusted store.
    if config.IS_PRODUCTION and redis_manager.backend != "redis":
        logger.error(
            "cleanup sweep SKIPPED: Redis backend is %r, not real 'redis' -- refusing to "
            "reap on an untrusted liveness store (would risk deleting live tenant data)",
            redis_manager.backend,
        )
        return result

    uploads_root = config.UPLOADS_DIR
    if not os.path.isdir(uploads_root):
        return result

    # Snapshot the catalog ONCE via a static query (no user input -- AP-8). We
    # drop from this snapshot; DROP ... IF EXISTS stays correct as we mutate.
    catalog_rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables"
    )
    catalog_names = [r[0] for r in (catalog_rows or [])]

    now = time.time()
    reclaimed_any = False

    for entry in os.listdir(uploads_root):
        dir_path = os.path.join(uploads_root, entry)
        if not os.path.isdir(dir_path):
            continue

        # Grace window: never reap a dir touched within the grace period -- an
        # in-flight upload's marker/table may not exist yet.
        try:
            age = now - os.path.getmtime(dir_path)
        except OSError:
            continue
        if age < config.SWEEP_GRACE_SECONDS:
            continue

        # A live marker means the session is still in use (even read-only) -- skip.
        if redis_manager.session_alive(entry):
            continue

        # --- reclaim this dead session ---
        # AP-8: `entry` (untrusted dir name) is NEVER put in SQL. We derive its
        # identifier prefixes and filter the catalog snapshot in Python; only
        # catalog-sourced, quote-escaped names reach DROP.
        uuid_ = entry.replace("-", "_")
        prefixes = (f"t_{uuid_}_", f"backup_{uuid_}_")
        victims = [name for name in catalog_names if name.startswith(prefixes)]
        for name in victims:
            await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_quote_ident(name)}")
            result["tables_dropped"] += 1
            reclaimed_any = True

        # Estimate reclaimed bytes before removing the dir.
        result["bytes_estimated"] += _dir_size(dir_path)
        shutil.rmtree(dir_path, ignore_errors=True)
        result["dirs_removed"] += 1
        reclaimed_any = True

        redis_manager.purge_session(entry)
        result["sessions_reaped"] += 1

    if reclaimed_any:
        # Reclaim freed space for reuse *within* spencer.db (the file may not
        # shrink on disk, but the space is reused -- that bounds a long-running VM).
        await db_manager.run_readwrite("CHECKPOINT")

    return result


async def reclaim_session_storage(session_uuid: str) -> dict:
    """Tear down ONE session's storage now: drop its DuckDB tables, purge its
    Redis keys, and remove its upload dir. Used by the owner-initiated
    ``DELETE /sessions/{uuid}`` (TASK-027); ``sweep()`` reclaims dead sessions on
    a timer with the same primitives. Idempotent.

    Security: same AP-8 discipline as sweep -- the (server-minted, but still
    treated as untrusted) uuid is NEVER interpolated into SQL. We snapshot the
    catalog, filter names in Python by the session's identifier prefix, and only
    ``DROP`` catalog-sourced, quote-escaped identifiers."""
    result = {"tables_dropped": 0, "dir_removed": False, "redis_keys_deleted": 0}

    catalog_rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables"
    )
    catalog_names = [r[0] for r in (catalog_rows or [])]

    uuid_ = session_uuid.replace("-", "_")
    prefixes = (f"t_{uuid_}_", f"backup_{uuid_}_")
    for name in catalog_names:
        if name.startswith(prefixes):
            await db_manager.run_readwrite(f"DROP TABLE IF EXISTS {_quote_ident(name)}")
            result["tables_dropped"] += 1

    result["redis_keys_deleted"] = redis_manager.purge_session(session_uuid)

    dir_path = os.path.join(config.UPLOADS_DIR, session_uuid)
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)
        result["dir_removed"] = True

    if result["tables_dropped"]:
        await db_manager.run_readwrite("CHECKPOINT")

    return result



async def storage_report() -> dict:
    """Point-in-time storage/liveness metrics for `GET /admin/storage`."""
    uploads_root = config.UPLOADS_DIR
    uploads_bytes = 0
    live_sessions = 0
    orphan_dirs = 0
    if os.path.isdir(uploads_root):
        for entry in os.listdir(uploads_root):
            dir_path = os.path.join(uploads_root, entry)
            if not os.path.isdir(dir_path):
                continue
            uploads_bytes += _dir_size(dir_path)
            if redis_manager.session_alive(entry):
                live_sessions += 1
            else:
                orphan_dirs += 1

    catalog_rows = await db_manager.run_readwrite(
        "SELECT table_name FROM information_schema.tables"
    )
    catalog_names = [r[0] for r in (catalog_rows or [])]
    table_count = sum(1 for n in catalog_names if n.startswith(("t_", "backup_")))

    try:
        db_bytes = os.path.getsize(DUCKDB_PATH)
    except OSError:
        db_bytes = 0

    usage = shutil.disk_usage(".")

    # Surface the live memory_limit so ops (and the TASK-013 proof) can confirm
    # the startup PRAGMA actually took effect on this connection.
    try:
        mem_rows = await db_manager.run_readwrite("SELECT current_setting('memory_limit')")
        memory_limit = mem_rows[0][0] if mem_rows else None
    except Exception:
        memory_limit = None

    return {
        "disk_free": usage.free,
        "disk_total": usage.total,
        "uploads_bytes": uploads_bytes,
        "db_bytes": db_bytes,
        "table_count": table_count,
        "live_sessions": live_sessions,
        "orphan_dirs": orphan_dirs,
        "duckdb_memory_limit": memory_limit,
    }


async def sweep_loop():
    """Background task: run sweep() every SWEEP_INTERVAL_SECONDS, forever. One
    failing sweep never kills the loop -- it is logged and retried next
    interval. Cancelled cleanly on shutdown (CancelledError is BaseException in
    3.11, so the broad Exception guard below does not swallow it)."""
    logger.info(
        "cleanup sweeper started (interval=%ss, grace=%ss, ttl=%sh)",
        config.SWEEP_INTERVAL_SECONDS,
        config.SWEEP_GRACE_SECONDS,
        config.SESSION_TTL_HOURS,
    )
    while True:
        # Sleep FIRST (S-2, TASK-029): do not sweep the instant the process boots.
        # A transient Redis lag at startup could otherwise drop us to the empty
        # fallback and have the very first sweep reap live data seconds later.
        # Waiting one interval lets Redis settle (and lets ops intervene).
        await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)
        try:
            counts = await sweep()
            if counts["sessions_reaped"]:
                logger.info("cleanup sweep reclaimed %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cleanup sweep failed; retrying next interval")
