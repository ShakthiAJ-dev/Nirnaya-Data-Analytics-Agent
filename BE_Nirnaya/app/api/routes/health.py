"""
app/api/routes/health.py
------------------------
Readiness / liveness health check endpoint.

GET /api/v1/health
  → Pings Supabase DB and Upstash Redis in parallel.
  → LLM health is intentionally excluded — LLM is a per-request factory
    keyed on caller-supplied API keys, so there is nothing server-side to ping.
  → Returns aggregate status: healthy | degraded | unhealthy
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_redis, get_supabase
from app.schemas.common import HealthStatus, ServiceHealthStatus
from app.services.redis_service import RedisService
from app.services.supabase_service import SupabaseService

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthStatus,
    summary="Deep health check",
    description=(
        "Checks connectivity to Supabase (DB) and Upstash Redis. "
        "LLM providers are excluded — they are caller-keyed, per-request clients."
    ),
)
async def health_check(
    request: Request,
    supabase: SupabaseService = Depends(get_supabase),
    redis: RedisService = Depends(get_redis),
) -> HealthStatus:
    from app.core.config import settings

    # Run both checks concurrently
    supabase_result, redis_result = await asyncio.gather(
        supabase.health_check(),
        redis.health_check(),
        return_exceptions=True,
    )

    services: list[ServiceHealthStatus] = []

    # --- Supabase ---
    if isinstance(supabase_result, Exception):
        services.append(
            ServiceHealthStatus(name="supabase", healthy=False, detail=str(supabase_result))
        )
    else:
        is_healthy, latency = supabase_result
        services.append(
            ServiceHealthStatus(name="supabase", healthy=is_healthy, latency_ms=round(latency, 2))
        )

    # --- Redis ---
    if isinstance(redis_result, Exception):
        services.append(
            ServiceHealthStatus(name="redis", healthy=False, detail=str(redis_result))
        )
    else:
        is_healthy, latency = redis_result
        services.append(
            ServiceHealthStatus(name="redis", healthy=is_healthy, latency_ms=round(latency, 2))
        )

    # Aggregate
    all_healthy = all(s.healthy for s in services)
    any_healthy = any(s.healthy for s in services)

    if all_healthy:
        status = "healthy"
    elif any_healthy:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthStatus(
        status=status,
        environment=settings.environment,
        services=services,
    )