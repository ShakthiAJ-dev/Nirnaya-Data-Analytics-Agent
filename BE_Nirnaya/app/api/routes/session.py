"""
app/api/routes/session.py
--------------------------
Session management endpoints.

POST /api/v1/session/init
    No auth required.
    Rate-limited by IP: SESSION_INIT_RATE_LIMIT requests / minute.
    Creates an anonymous session in Redis, returns a signed bearer token.

POST /api/v1/session/llm-provider-key
    Requires Authorization: Bearer <token>.
    Validates the API key against the provider (live round-trip), then
    encrypts and stores it in Redis under the session.
    Never echoes the key back. Responds { status: 'stored' }.

Security notes
    - Token is validated on every protected request (not just at login).
    - Bedrock path skips validation (server key, not user-supplied).
    - API key is never logged, never returned, deleted from scope immediately.
"""

from __future__ import annotations
from typing import Any

import re

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import RateLimitException, SessionException, ValidationException
from app.core.logging import get_logger
from app.schemas.session import (
    AvailableModelsResponse,
    LLMProviderKeyRequest,
    LLMProviderKeyResponse,
    ModelInfo,
    SessionInitResponse,
)
from app.services.session_service import SessionService, verify_token

logger = get_logger(__name__)


router = APIRouter(prefix="/session", tags=["Session"])



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bearer_token(request: Request) -> str:
    """Extract the bearer token from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise SessionException("Missing or malformed Authorization header.")
    return auth.removeprefix("Bearer ").strip()


async def _require_session(
    request: Request,
    redis: RedisDep,
) -> tuple[str, SessionService]:
    """
    Dependency: validate bearer token, verify session exists in Redis.
    Returns (session_id, SessionService).
    """
    token = _get_bearer_token(request)
    session_id = verify_token(token)
    if session_id is None:
        raise SessionException("Invalid or expired session token.")

    svc = get_session_service(redis)
    session = await svc.get_session(session_id)
    if session is None:
        raise SessionException("Session not found or expired.")

    # Slide TTL on every authenticated request
    await svc.refresh_session(session_id)
    return session_id, svc


# ---------------------------------------------------------------------------
# Key-format validators (loose — just catch obvious garbage before the network call)
# ---------------------------------------------------------------------------

_OPENAI_PREFIX = re.compile(r"^sk-")
_ANTHROPIC_PREFIX = re.compile(r"^sk-ant-")


def _validate_key_format(provider: str, api_key: str) -> None:
    """Raises ValidationException if the key format is clearly wrong."""
    if provider == "openai":
        if not _OPENAI_PREFIX.match(api_key) or len(api_key) < 20:
            raise ValidationException(
                "OpenAI API keys must start with 'sk-' and be at least 20 characters."
            )
    elif provider == "anthropic":
        if not _ANTHROPIC_PREFIX.match(api_key) or len(api_key) < 20:
            raise ValidationException(
                "Anthropic API keys must start with 'sk-ant-' and be at least 20 characters."
            )


# ---------------------------------------------------------------------------
# POST /session/init
# ---------------------------------------------------------------------------

@router.post(
    "/init",
    response_model=SessionInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new anonymous session",
    description=(
        "Creates a new session in Redis and returns a signed bearer token. "
        "No authentication required. Rate-limited by IP."
    ),
)
async def session_init(
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    # Rate-limit by IP
    client_ip = request.client.host if request.client else "unknown"
    allowed, remaining = await redis.rate_limit(
        f"ip:{client_ip}:session_init",
        limit=settings.session_init_rate_limit,
        window_seconds=60,
    )
    if not allowed:
        raise RateLimitException(
            "Too many session creation requests. Please wait before trying again."
        )

    svc = get_session_service(redis)
    session_id, token = await svc.create_session()

    logger.info(
        "session_init_success",
        session_id=session_id,
        client_ip=client_ip,
        remaining_quota=remaining,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "session_id": session_id,
            "token": token,
            "expires_in": settings.session_ttl,
        },
    )


# ---------------------------------------------------------------------------
# POST /session/llm-provider-key
# ---------------------------------------------------------------------------

@router.post(
    "/llm-provider-key",
    response_model=LLMProviderKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit and store your LLM provider API key",
    description=(
        "Validates the supplied API key against the provider (live check), "
        "then encrypts and stores it in Redis for the duration of the session. "
        "The key is never echoed back. Bedrock provider uses the server-side key "
        "and does not require a user-supplied key."
    ),
)
async def submit_llm_key(
    body: LLMProviderKeyRequest,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    session_id, svc = await _require_session(request, redis)

    provider = body.provider
    api_key = body.api_key

    # Bedrock: server-managed key, nothing to store from the user
    if provider == "anthropic" and settings.claude_provider == "bedrock":
        if not settings.bedrock_api_key:
            from app.core.exceptions import LLMException
            raise LLMException(
                "BEDROCK_API_KEY is not configured on the server. "
                "Contact the administrator."
            )
        # Nothing to store — Bedrock key is server-side only
        logger.info("llm_key_bedrock_server_key_in_use", session_id=session_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "stored"},
        )

    # Loose format check before burning a network round-trip
    _validate_key_format(provider, api_key)

    # Live key validation
    valid = False
    if provider == "openai":
        valid = await svc.validate_openai_key(api_key)
    elif provider == "anthropic":
        valid = await svc.validate_anthropic_key(api_key)

    if not valid:
        # Scrub key from local scope — do NOT include it in the exception message
        del api_key
        raise ValidationException(
            f"The provided {provider} API key could not be validated. "
            "Check that the key is correct and has not been revoked."
        )

    # Encrypt and persist
    await svc.store_api_key(session_id, provider, api_key)
    del api_key  # scrub plaintext immediately

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "stored"},
    )


# ---------------------------------------------------------------------------
# GET /session/models (and /session/available-models)
# ---------------------------------------------------------------------------

@router.get(
    "/models",
    response_model=AvailableModelsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get available LLM models for the current session",
    description=(
        "Returns the list of usable models based on stored session API keys and "
        "server configurations (e.g. Bedrock). Requires Bearer token authentication."
    ),
)
@router.get(
    "/available-models",
    response_model=AvailableModelsResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_available_models(
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    session_id, svc = await _require_session(request, redis)

    models: list[dict[str, Any]] = []

    # 1. Check Anthropic availability
    # Bedrock mode uses the server-configured Bedrock key.
    # Direct mode uses session-stored Anthropic key.
    has_anthropic = False
    if settings.claude_provider == "bedrock" and settings.bedrock_api_key:
        has_anthropic = True
    elif await svc.has_api_key(session_id, "anthropic"):
        has_anthropic = True

    if has_anthropic:
        models.extend([
            {
                "id": "claude-4.5-sonnet",
                "name": "Claude 4.5 Sonnet",
                "provider": "anthropic",
                "description": "Anthropic's flagship intelligent model for complex reasoning and agent workflows.",
            },
            {
                "id": "claude-4.5-haiku",
                "name": "Claude 4.5 Haiku",
                "provider": "anthropic",
                "description": "Ultra-fast and lightweight model for high-throughput tasks.",
            }
        ])

    # 2. Check OpenAI availability
    if await svc.has_api_key(session_id, "openai"):
        models.extend([
            {
                "id": "gpt-5.4",
                "name": "GPT-5.4",
                "provider": "openai",
                "description": "Next-generation OpenAI frontier intelligence model.",
            },
            {
                "id": "gpt-5.4-mini",
                "name": "GPT-5.4 Mini",
                "provider": "openai",
                "description": "Fast and cost-efficient OpenAI model for structured agent execution.",
            }
        ])

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"models": models},
    )