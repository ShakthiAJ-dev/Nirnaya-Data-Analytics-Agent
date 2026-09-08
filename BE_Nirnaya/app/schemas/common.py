"""
app/schemas/common.py
---------------------
Shared Pydantic response models used across the entire Nirnaya API.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic success wrapper
# ---------------------------------------------------------------------------
class SuccessResponse(BaseModel, Generic[T]):
    """Standard envelope for successful API responses."""

    success: Literal[True] = True
    data: T
    message: str | None = None


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    meta: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard envelope for error responses."""

    success: Literal[False] = False
    error: ErrorDetail


# ---------------------------------------------------------------------------
# Health / readiness models
# ---------------------------------------------------------------------------
class ServiceHealthStatus(BaseModel):
    """Per-service health detail."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    detail: str | None = None


class HealthStatus(BaseModel):
    """Aggregate health response from GET /api/v1/health."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str = Field(default="1.0.0")
    environment: str
    services: list[ServiceHealthStatus] = Field(default_factory=list)
