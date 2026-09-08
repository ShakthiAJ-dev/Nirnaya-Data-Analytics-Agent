"""
app/schemas/session.py
-----------------------
Pydantic models for session management endpoints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionInitResponse(BaseModel):
    """Response from POST /session/init."""

    session_id: str
    token: str
    expires_in: int = Field(description="Token lifetime in seconds.")


class LLMProviderKeyRequest(BaseModel):
    """Body for POST /session/llm-provider-key."""

    provider: Literal["openai", "anthropic"] = Field(
        description="LLM provider whose key is being submitted."
    )
    api_key: str = Field(
        min_length=1,
        description="The caller's LLM API key. Encrypted at rest; never echoed back.",
    )


class LLMProviderKeyResponse(BaseModel):
    """Response from POST /session/llm-provider-key."""

    status: Literal["stored"] = "stored"


class ModelInfo(BaseModel):
    """Metadata for an available LLM model."""

    id: str = Field(description="Model identifier to pass in requests.")
    name: str = Field(description="Human-readable model name.")
    provider: Literal["openai", "anthropic"] = Field(description="LLM provider name.")
    description: str = Field(default="", description="Short description of the model capability.")


class AvailableModelsResponse(BaseModel):
    """Response from GET /session/models."""

    models: list[ModelInfo] = Field(description="List of currently available models based on active keys.")