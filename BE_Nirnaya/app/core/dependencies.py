"""
app/core/dependencies.py
------------------------
FastAPI dependency-injection helpers.

Singleton services (Supabase, Redis, WSManager) live on app.state and are
pulled here via Depends().

SessionService is constructed per-request (thin wrapper around RedisService)
via get_session_service().

LLMService is NOT injected as a dependency — use LLMService.from_session()
directly inside WS handlers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.services.redis_service import RedisService
from app.services.session_service import SessionService
from app.services.supabase_service import SupabaseService
from app.services.ws_manager import WSManager


# ---------------------------------------------------------------------------
# Service injectors — pull singletons from app.state
# ---------------------------------------------------------------------------

def get_supabase(request: Request) -> SupabaseService:
    """Inject the shared SupabaseService instance."""
    return request.app.state.supabase_service


def get_redis(request: Request) -> RedisService:
    """Inject the shared RedisService instance."""
    return request.app.state.redis_service


def get_ws_manager(request: Request) -> WSManager:
    """Inject the shared WSManager instance."""
    return request.app.state.ws_manager


# ---------------------------------------------------------------------------
# Type aliases for cleaner route signatures
# ---------------------------------------------------------------------------

SupabaseDep = Annotated[SupabaseService, Depends(get_supabase)]
RedisDep = Annotated[RedisService, Depends(get_redis)]
WSManagerDep = Annotated[WSManager, Depends(get_ws_manager)]


def get_session_service(redis: RedisDep) -> SessionService:
    """
    Per-request SessionService factory.
    Wraps the shared RedisService — no state of its own.
    """
    return SessionService(redis)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]

