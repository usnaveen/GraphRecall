"""Pluggable rate limiting for the agent bridge.

``RateLimiter.hit(bucket, limit, window_seconds)`` counts one event in ``bucket`` and
returns False once ``limit`` events happened in the current window.

Backends (``AGENT_BRIDGE_RATE_LIMIT_BACKEND``):

* ``memory``   - per-process sliding window (dev/tests; default outside production)
* ``postgres`` - shared fixed-window counters in ``agent_rate_limits`` (default when
                 ``ENVIRONMENT=production``); correct across workers/instances
* ``redis``    - INCR + EXPIRE fixed window, used when ``REDIS_URL`` is set and the
                 ``redis`` package is installed

Limits (env overrides):

| env | default | bucket |
|---|---|---|
| ``AGENT_BRIDGE_MCP_CALLS_PER_MIN`` | 120 | per agent key, every MCP request |
| ``AGENT_BRIDGE_ENQUEUE_PER_HOUR`` | 20 | per user, ``POST /requests`` |
| ``AGENT_BRIDGE_PROPOSALS_PER_KEY_PER_DAY`` | 100 | per agent key, new feed items |
| ``AGENT_BRIDGE_MAX_PENDING_PER_DAY`` | 50 | per user, pending items created today (DB count) |
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Any, Optional, Protocol

import structlog

logger = structlog.get_logger()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def mcp_calls_per_min() -> int:
    return _int_env("AGENT_BRIDGE_MCP_CALLS_PER_MIN", 120)


def enqueue_per_hour() -> int:
    return _int_env("AGENT_BRIDGE_ENQUEUE_PER_HOUR", 20)


def proposals_per_key_per_day() -> int:
    return _int_env("AGENT_BRIDGE_PROPOSALS_PER_KEY_PER_DAY", 100)


def max_pending_per_day() -> int:
    return _int_env("AGENT_BRIDGE_MAX_PENDING_PER_DAY", 50)


class RateLimiter(Protocol):
    async def hit(self, bucket: str, limit: int, window_seconds: int, cost: int = 1) -> bool: ...


class InMemoryRateLimiter:
    """Sliding window, per process. Fine for dev/tests and single-worker deploys."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, bucket: str, limit: int, window_seconds: int, cost: int = 1,
                  now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits[bucket]
        while q and now - q[0] >= window_seconds:
            q.popleft()
        if len(q) + cost > limit:
            return False
        q.extend([now] * cost)
        return True


class PostgresRateLimiter:
    """Fixed-window counters shared by all workers (table ``agent_rate_limits``).

    One atomic upsert per hit; rows older than a day can be deleted by the sweep job.
    """

    def __init__(self, pg_client: Any):
        self.pg = pg_client

    async def hit(self, bucket: str, limit: int, window_seconds: int, cost: int = 1) -> bool:
        window_start = int(time.time()) // window_seconds * window_seconds
        rows = await self.pg.execute_query(
            """
            INSERT INTO agent_rate_limits (bucket, window_start, hits)
            VALUES (:bucket, to_timestamp(:ws), :cost)
            ON CONFLICT (bucket, window_start)
            DO UPDATE SET hits = agent_rate_limits.hits + EXCLUDED.hits
            RETURNING hits
            """,
            {"bucket": bucket, "ws": window_start, "cost": cost},
        )
        return int(rows[0]["hits"]) <= limit


class RedisRateLimiter:  # pragma: no cover - needs a Redis server
    def __init__(self, url: str):
        import redis.asyncio as redis  # optional dependency

        self.r = redis.from_url(url)

    async def hit(self, bucket: str, limit: int, window_seconds: int, cost: int = 1) -> bool:
        window_start = int(time.time()) // window_seconds * window_seconds
        key = f"gr:agent:rl:{bucket}:{window_start}"
        pipe = self.r.pipeline()
        pipe.incrby(key, cost)
        pipe.expire(key, window_seconds + 5)
        hits, _ = await pipe.execute()
        return int(hits) <= limit


def limiter_from_env(pg_client: Any = None) -> RateLimiter:
    from backend.agent_bridge.keys import is_production

    backend = os.environ.get("AGENT_BRIDGE_RATE_LIMIT_BACKEND", "").strip().lower()
    if not backend:
        backend = "redis" if os.environ.get("REDIS_URL") else (
            "postgres" if is_production() else "memory")
    if backend == "redis" and os.environ.get("REDIS_URL"):
        try:
            return RedisRateLimiter(os.environ["REDIS_URL"])
        except ImportError:
            logger.warning("agent_bridge: redis package missing; falling back to postgres")
            backend = "postgres"
    if backend == "postgres" and pg_client is not None:
        return PostgresRateLimiter(pg_client)
    return _shared_memory_limiter


_shared_memory_limiter = InMemoryRateLimiter()
