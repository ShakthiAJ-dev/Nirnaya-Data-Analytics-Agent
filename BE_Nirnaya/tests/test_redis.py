"""
tests/test_redis.py
-------------------
Quick smoke-test for RedisService.

Run with:
    cd BE_Nirnaya
    python -m tests.test_redis
"""

import asyncio
import sys
import os

# Make sure the BE_Nirnaya package root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.redis_service import RedisService


async def main() -> None:
    svc = RedisService()

    # ── 1. Initialize (connects to Redis via REDIS_URL in .env) ──────────
    print("Initializing RedisService...")
    await svc.initialize()
    print("✓ Connected to Redis\n")

    # ── 2. Health check ──────────────────────────────────────────────────
    healthy, latency_ms = await svc.health_check()
    print(f"Health check → healthy={healthy}, latency={latency_ms:.1f} ms\n")

    # ── 3. Cache: set / get / delete ─────────────────────────────────────
    await svc.cache_set("test:greeting", {"msg": "hello from Nirnaya"}, ttl=60)
    print("cache_set  → stored {'msg': 'hello from Nirnaya'}")

    value = await svc.cache_get("test:greeting")
    print(f"cache_get  → {value}")

    deleted = await svc.cache_delete("test:greeting")
    print(f"cache_delete → {deleted} key(s) removed\n")

    # ── 4. Session: set / get / delete ───────────────────────────────────
    await svc.session_set("sid:demo", {"user_id": "u_001", "role": "admin"}, ttl=300)
    print("session_set → stored session for sid:demo")

    session = await svc.session_get("sid:demo")
    print(f"session_get → {session}")

    await svc.session_delete("sid:demo")
    print("session_delete → session removed\n")

    # ── 5. Rate limiting ─────────────────────────────────────────────────
    for i in range(3):
        allowed, remaining = await svc.rate_limit("test:user:1", limit=5, window_seconds=10)
        print(f"rate_limit call {i+1} → allowed={allowed}, remaining={remaining}")

    # ── 6. Close ─────────────────────────────────────────────────────────
    await svc.close()
    print("\n✓ RedisService closed. All tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
