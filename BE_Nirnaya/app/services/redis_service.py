"""
app/services/redis_service.py
------------------------------
Upstash Redis integration using `redis.asyncio` over TLS (rediss://).

Three functional areas:
  1. Cache   — cache_get / cache_set / cache_delete / cache_clear_prefix
  2. Rate Limiting — sliding-window rate limiter via sorted sets
  3. Sessions — JSON-serialised user sessions with TTL

All methods are async and safe for concurrent use — the underlying
connection pool handles multiplexing.

Usage:
    from app.services import redis_service

    # Cache
    await redis_service.cache_set("key", {"data": 1}, ttl=300)
    value = await redis_service.cache_get("key")

    # Rate limit
    allowed, remaining = await redis_service.rate_limit("user:abc", limit=60, window=60)
    if not allowed:
        raise RateLimitException("Too many requests")

    # Session
    await redis_service.session_set("sid:xyz", {"user_id": "abc"}, ttl=86400)
    session = await redis_service.session_get("sid:xyz")
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool

from app.core.config import settings
from app.core.exceptions import RateLimitException
from app.core.logging import get_logger

logger = get_logger(__name__)

_CACHE_PREFIX = "nirnaya:cache:"
_RATE_PREFIX = "nirnaya:rate:"
_SESSION_PREFIX = "nirnaya:session:"


class RedisService:
    """
    Thin async wrapper around redis.asyncio.
    Initialise once in lifespan; attach to app.state.
    """

    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None
        self._client: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def initialize(self) -> None:
        """Called inside lifespan startup."""
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is not configured.")

        self._pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=True,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)

        # Verify connection
        await self._client.ping()
        logger.info("redis_service_ready", max_connections=settings.redis_max_connections)

    async def close(self) -> None:
        """Graceful shutdown — called inside lifespan teardown."""
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.aclose()
        logger.info("redis_service_closed")

    @property
    def client(self) -> aioredis.Redis:  # type: ignore[type-arg]
        if not self._client:
            raise RuntimeError("RedisService is not initialised.")
        return self._client

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    async def cache_get(self, key: str) -> Any | None:
        """
        Retrieve a cached value.
        Returns the deserialised value or None on miss.
        """
        raw = await self.client.get(f"{_CACHE_PREFIX}{key}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def cache_set(
        self,
        key: str,
        value: Any,
        *,
        ttl: int | None = None,
    ) -> None:
        """
        Store `value` under `key`.
        `ttl` defaults to settings.redis_default_ttl (seconds).
        """
        raw = json.dumps(value) if not isinstance(value, str) else value
        _ttl = ttl if ttl is not None else settings.redis_default_ttl
        await self.client.set(f"{_CACHE_PREFIX}{key}", raw, ex=_ttl)

    async def cache_delete(self, key: str) -> int:
        """Delete a cache key. Returns number of keys deleted."""
        return await self.client.delete(f"{_CACHE_PREFIX}{key}")

    async def cache_clear_prefix(self, prefix: str) -> int:
        """
        Delete all cache keys matching `prefix`.
        Uses SCAN — safe for production (no KEYS command).
        """
        pattern = f"{_CACHE_PREFIX}{prefix}*"
        deleted = 0
        async for key in self.client.scan_iter(pattern):
            await self.client.delete(key)
            deleted += 1
        return deleted

    # ------------------------------------------------------------------
    # Rate limiting — sliding window via sorted sets
    # ------------------------------------------------------------------

    async def rate_limit(
        self,
        identifier: str,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> tuple[bool, int]:
        """
        Sliding-window rate limiter.

        Args:
            identifier: unique key (e.g. "user:<id>", "ip:<ip>")
            limit:          max requests per window (default: settings value)
            window_seconds: window size in seconds (default: settings value)

        Returns:
            (allowed: bool, remaining: int)
                allowed   — True if the request should proceed
                remaining — requests left in the current window
        """
        _limit = limit or settings.rate_limit_requests
        _window = window_seconds or settings.rate_limit_window_seconds

        key = f"{_RATE_PREFIX}{identifier}"
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (_window * 1000)

        pipe = self.client.pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(key, "-inf", window_start_ms)
        # Count requests in window
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now_ms): now_ms})
        # Set expiry
        pipe.expire(key, _window + 1)

        results = await pipe.execute()
        current_count: int = results[1]

        if current_count >= _limit:
            # Remove the entry we just added — request is rejected
            await self.client.zrem(key, str(now_ms))
            return False, 0

        remaining = max(0, _limit - current_count - 1)
        return True, remaining

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def session_get(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve a session by ID. Returns None if not found / expired."""
        raw = await self.client.get(f"{_SESSION_PREFIX}{session_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def session_set(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl: int = 86400,  # 24 hours
    ) -> None:
        """Persist a session. Overwrites any existing session with the same ID."""
        await self.client.set(
            f"{_SESSION_PREFIX}{session_id}",
            json.dumps(data),
            ex=ttl,
        )

    async def session_delete(self, session_id: str) -> int:
        """Invalidate a session. Returns 1 if deleted, 0 if not found."""
        return await self.client.delete(f"{_SESSION_PREFIX}{session_id}")

    async def session_refresh(self, session_id: str, *, ttl: int = 86400) -> bool:
        """Extend the TTL of an existing session. Returns True on success."""
        result = await self.client.expire(f"{_SESSION_PREFIX}{session_id}", ttl)
        return bool(result)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> tuple[bool, float]:
        """
        PING the Redis server.
        Returns (is_healthy, latency_ms).
        """
        t0 = time.monotonic()
        try:
            await self.client.ping()
            return True, (time.monotonic() - t0) * 1000
        except Exception:
            return False, (time.monotonic() - t0) * 1000
