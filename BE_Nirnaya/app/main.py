"""
app/main.py
-----------
Nirnaya API — FastAPI application entry point.

Startup (lifespan):
  1. Configure structured logging
  2. Initialise SupabaseService → app.state.supabase_service
  3. Initialise RedisService    → app.state.redis_service

  NOTE: LLMService is a per-request factory — it is NOT initialised here.

Shutdown (lifespan):
  1. Close RedisService
  2. Close SupabaseService

Middleware (outermost → innermost):
  • Request-ID  — injects X-Request-ID header for distributed tracing
  • CORS        — configurable allow-list from settings
  • GZip        — compresses responses > 1 KB
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.session import router as session_router
from app.api.routes.projects import router as projects_router
from app.api.routes.databases import router as databases_router
from app.websocket.ws_agent import router as ws_agent_router
from app.services.database_service import DatabaseService
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.services.redis_service import RedisService
from app.services.supabase_service import SupabaseService
from app.services.ws_manager import WSManager

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup & shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────────────────
    configure_logging()
    logger.info("nirnaya_startup", environment=settings.environment, version="1.0.0")

    # Supabase
    supabase_service = SupabaseService()
    await supabase_service.initialize()
    app.state.supabase_service = supabase_service

    # Redis
    redis_service = RedisService()
    await redis_service.initialize()
    app.state.redis_service = redis_service

    # WebSocket task manager (in-process, no I/O needed)
    app.state.ws_manager = WSManager()

    # Create app tables (projects, databases, file_uploads) if absent
    await DatabaseService.initialize_app_tables(supabase_service)

    logger.info("nirnaya_services_ready", services=["supabase", "redis", "ws_manager"])

    yield  # ← application handles requests here

    # ── SHUTDOWN ─────────────────────────────────────────────────────────
    logger.info("nirnaya_shutdown_started")
    await redis_service.close()
    await supabase_service.close()
    logger.info("nirnaya_shutdown_complete")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Nirnaya — AI-powered data analytics backend. "
        "LLM calls are per-request (caller-supplied API keys). "
        "Infrastructure: Supabase (Auth, DB, Storage, Realtime) + Upstash Redis."
    ),
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
register_exception_handlers(app)

# ---------------------------------------------------------------------------
# Middleware (last added = outermost wrapper)
# ---------------------------------------------------------------------------

# 1. GZip — compress large responses
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 2. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# 3. Request-ID — propagate or generate a unique request ID
@app.middleware("http")
async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(session_router, prefix=settings.api_v1_prefix)
app.include_router(projects_router, prefix=settings.api_v1_prefix)
app.include_router(databases_router, prefix=settings.api_v1_prefix)
app.include_router(ws_agent_router)  # /ws/agent — no api/v1 prefix


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/", tags=["Root"], include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "Nirnaya API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if not settings.is_production else "disabled",
    }