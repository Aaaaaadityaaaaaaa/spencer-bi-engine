import json
import os
import logging
from typing import Any, Dict, Optional

import redis
import fakeredis

import config

logger = logging.getLogger("spencer.redis")


class RedisManager:
    """Redis wrapper that uses a real redis-server when one is reachable and
    transparently falls back to an in-process fakeredis instance otherwise.

    `self.backend` is "redis" or "fakeredis" so callers/tests can report which
    store actually served a request -- no ambiguity when pasting proofs.

    Real Redis target defaults to localhost:6379 (Memurai / redis-server /
    docker-compose all expose that), overridable via REDIS_HOST / REDIS_PORT.
    """

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, db: int = 0):
        host = host or os.getenv("REDIS_HOST", "localhost")
        port = port or int(os.getenv("REDIS_PORT", "6379"))
        self.backend = "fakeredis"
        try:
            kwargs = dict(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            # Force RESP2. redis-py >= 8 negotiates RESP3 via a `HELLO 3`
            # handshake, which Redis < 6 rejects ("unknown command `HELLO`") --
            # that would silently drop us to fakeredis against an older server.
            # Spencer only uses string/TTL ops, so RESP2 costs us nothing and
            # keeps compatibility with any Redis 2.6+.
            try:
                client = redis.Redis(protocol=2, **kwargs)
            except TypeError:
                # redis-py too old to know the `protocol` kwarg: it is RESP2 anyway.
                client = redis.Redis(**kwargs)
            client.ping()
            self.client = client
            self.backend = "redis"
            server_ver = "unknown"
            try:
                server_ver = client.info("server").get("redis_version", "unknown")
            except Exception:
                pass
            self.server_version = server_ver
            logger.info("RedisManager connected to real redis %s at %s:%s", server_ver, host, port)
        except Exception as exc:  # ConnectionError, timeout, ResponseError, etc.
            # S-2 (TASK-029): in production, do NOT silently fall back to the empty
            # in-memory fakeredis. Redis holds the session liveness markers the
            # cleanup sweeper trusts; booting on an empty store would make the first
            # sweep treat every live session as dead and delete all tenant data.
            # Fail hard so the deploy is fixed before any data is ever at risk.
            if config.IS_PRODUCTION:
                raise RuntimeError(
                    f"Refusing to start: SPENCER_ENV=production but Redis is unreachable at "
                    f"{host}:{port} ({type(exc).__name__}: {exc}). Redis is required in "
                    f"production (it holds session liveness the sweeper trusts). Start Redis "
                    f"or fix REDIS_HOST/REDIS_PORT."
                ) from exc
            self.client = fakeredis.FakeRedis(decode_responses=True)
            self.server_version = None
            logger.warning("RedisManager falling back to fakeredis (%s: %s)", type(exc).__name__, exc)

    def set_json(self, key: str, value: Dict[str, Any], ttl: int = None):
        # default=str so DATE/TIMESTAMP/Decimal sample values from DuckDB
        # (which are not natively JSON-serializable) never crash the cache write.
        payload = json.dumps(value, default=str)
        if ttl:
            self.client.setex(key, ttl, payload)
        else:
            self.client.set(key, payload)

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        val = self.client.get(key)
        if val:
            return json.loads(val)
        return None

    def incr_version(self, session_uuid: str) -> int:
        """Atomically bump and return the schema version for a session. Called
        after every transform/undo/redo so any query result cached against an
        older version is treated as stale (ARCHITECTURE.md)."""
        return int(self.client.incr(f"schema_version:{session_uuid}"))

    def get_version(self, session_uuid: str) -> int:
        val = self.client.get(f"schema_version:{session_uuid}")
        return int(val) if val else 0

    # --- Business-dictionary version (Phase 6) -------------------------------
    # The Custom Instructions bizdict feeds the NL->SQL prompt, so a term
    # add/delete must invalidate cached AI SQL exactly like a schema change does.
    # Mirrors incr_version/get_version, keyed `bizdict_version:{session}`.
    def incr_bizdict_version(self, session_uuid: str) -> int:
        return int(self.client.incr(f"bizdict_version:{session_uuid}"))

    def get_bizdict_version(self, session_uuid: str) -> int:
        val = self.client.get(f"bizdict_version:{session_uuid}")
        return int(val) if val else 0

    # --- AI NL->SQL result cache (Phase 6) -----------------------------------
    # Keys are version-stamped (DATABASE.md): a question resolved against schema
    # v3 + bizdict v2 lives at query:{qh}:3:2. When either version INCRs, the old
    # key is simply never read again -- no explicit invalidation, no stale hit.
    #   query:{qh}:{sv}:{bv}  -> the generated SQL   (no TTL; version-keyed)
    #   fail:{qh}:{sv}:{bv}   -> a cached failure     (TTL 300s; bounds token burn)
    @staticmethod
    def _query_key(question_hash: str, schema_version: int, bizdict_version: int) -> str:
        return f"query:{question_hash}:{schema_version}:{bizdict_version}"

    @staticmethod
    def _fail_key(question_hash: str, schema_version: int, bizdict_version: int) -> str:
        return f"fail:{question_hash}:{schema_version}:{bizdict_version}"

    def get_sql_cache(self, question_hash: str, schema_version: int, bizdict_version: int) -> Optional[str]:
        # decode_responses=True on both real + fakeredis, so this is a str or None.
        return self.client.get(self._query_key(question_hash, schema_version, bizdict_version))

    def set_sql_cache(self, question_hash: str, schema_version: int, bizdict_version: int, sql: str) -> None:
        self.client.set(self._query_key(question_hash, schema_version, bizdict_version), sql)

    def get_fail_cache(self, question_hash: str, schema_version: int, bizdict_version: int) -> Optional[Dict[str, Any]]:
        val = self.client.get(self._fail_key(question_hash, schema_version, bizdict_version))
        return json.loads(val) if val else None

    def set_fail_cache(
        self,
        question_hash: str,
        schema_version: int,
        bizdict_version: int,
        error: Dict[str, Any],
        ttl: int = 300,
    ) -> None:
        self.client.setex(self._fail_key(question_hash, schema_version, bizdict_version), ttl, json.dumps(error))

    # --- Session lifecycle / liveness marker (TASK-013) ----------------------
    # `session:{uuid}` (value "1") with a *sliding* TTL defines the "session
    # lifetime" the DATABASE.md schema previously listed as an undefined gap.
    # touch_session is called on create/upload and on every `/sessions/{uuid}/...`
    # request (main.py middleware) so an actively-used session -- including
    # read-only queries -- never ages out. The cleanup sweep reaps any session
    # whose marker has expired.
    def touch_session(self, session_uuid: str, ttl: int) -> None:
        """Create/refresh the liveness marker with a sliding TTL (atomic SET+EXPIRE)."""
        self.client.set(f"session:{session_uuid}", "1", ex=ttl)

    def refresh_session(self, session_uuid: str, ttl: int) -> bool:
        """Slide the TTL on an *existing* marker without creating one. Used by
        the request middleware so activity keeps a live session alive, while a
        request to a bogus/reaped uuid does NOT resurrect a marker (returns
        False -- EXPIRE on a missing key is a no-op). Data-creating routes use
        touch_session (SET+EXPIRE) instead."""
        return bool(self.client.expire(f"session:{session_uuid}", ttl))

    def session_alive(self, session_uuid: str) -> bool:
        """True iff the session's liveness marker still exists (has not expired)."""
        return bool(self.client.exists(f"session:{session_uuid}"))

    def purge_session(self, session_uuid: str) -> int:
        """Delete every Redis key owned by a session. Returns the count actually
        removed -- idempotent, so a second call returns 0. Deleting keys that
        were never written (e.g. joins:/bizdict:) is a harmless no-op."""
        keys = [
            f"schema:{session_uuid}",
            f"bizdict:{session_uuid}",
            f"joins:{session_uuid}",
            f"schema_version:{session_uuid}",
            f"bizdict_version:{session_uuid}",
            f"session:{session_uuid}",
        ]
        return int(self.client.delete(*keys))

    def pin_schema(self, session_uuid: str, schedule_id: str):
        # Phase 7 (scheduling) -- pins a schema version to a scheduled job so a
        # later run resolves against the same schema. Not part of Phase 6.
        pass


redis_manager = RedisManager()
