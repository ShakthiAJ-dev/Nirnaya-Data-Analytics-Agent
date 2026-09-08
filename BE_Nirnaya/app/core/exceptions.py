"""
app/core/exceptions.py
----------------------
Domain exception hierarchy + FastAPI exception handlers.

All custom exceptions derive from NirnayaException so callers can
catch any service error with a single `except NirnayaException`.

Handlers are registered in main.py via:
    from app.core.exceptions import register_exception_handlers
    register_exception_handlers(app)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class NirnayaException(Exception):
    """Base exception for all Nirnaya application errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class LLMException(NirnayaException):
    """Raised when an LLM provider call fails."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "LLM_ERROR"


class LLMRateLimitException(LLMException):
    """Raised when an LLM provider returns a rate-limit error."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "LLM_RATE_LIMIT"


class DatabaseException(NirnayaException):
    """Raised when a Supabase / Postgres operation fails."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "DATABASE_ERROR"


class AuthException(NirnayaException):
    """Raised for authentication / authorisation failures."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "AUTH_ERROR"


class SessionException(NirnayaException):
    """Raised when a session token is invalid, expired, or missing."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "SESSION_ERROR"


class PermissionException(NirnayaException):
    """Raised when the caller lacks required permissions."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "PERMISSION_DENIED"


class RateLimitException(NirnayaException):
    """Raised when the application-level rate limit is exceeded."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"


class NotFoundException(NirnayaException):
    """Raised when a requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ValidationException(NirnayaException):
    """Raised for business-logic validation failures."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": error_code,
                "message": message,
                "meta": detail,
            },
        },
    )


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

async def _nirnaya_exception_handler(
    request: Request, exc: NirnayaException
) -> JSONResponse:
    logger.warning(
        "nirnaya_exception",
        error_code=exc.error_code,
        message=exc.message,
        path=str(request.url),
        detail=exc.detail,
    )
    return _error_response(exc.status_code, exc.error_code, exc.message, exc.detail)


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    logger.warning("validation_error", path=str(request.url), errors=errors)
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "Request validation failed.",
        {"errors": errors},
    )


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        path=str(request.url),
        exc_info=exc,
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An internal server error occurred.",
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app instance."""
    app.add_exception_handler(NirnayaException, _nirnaya_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)  # type: ignore[arg-type]
