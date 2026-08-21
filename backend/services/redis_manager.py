import json
import os
import logging
from typing import Any, Dict, Optional

import redis
import fakeredis

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

    def get_query_cache(self, question_hash: str, schema_version: int, bizdict_version: int):
        pass

    def pin_schema(self, session_uuid: str, schedule_id: str):
        pass


redis_manager = RedisManager()
