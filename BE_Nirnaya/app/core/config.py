"""
app/core/config.py
------------------
Centralised settings loaded from a .env file (dev) or OS environment variables
(staging / production). Pydantic-settings merges both — OS env vars take
precedence over .env values.

Every field uses `validation_alias` to make the exact .env key explicit.
LLM API keys are NOT stored in this file — they are submitted by the caller once,
encrypted with AES-256-GCM, and stored in Redis for the session lifetime.
The only permanent server-side LLM credential is BEDROCK_API_KEY (Bedrock path).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = Field(default="Nirnaya API", validation_alias="APP_NAME")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", validation_alias="ENVIRONMENT"
    )
    debug: bool = Field(default=False, validation_alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    # Stored as a raw comma-separated string so pydantic-settings does not
    # attempt to JSON-decode it from the .env file.
    # Use settings.cors_origins_list in code.
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        validation_alias="CORS_ORIGINS",
    )
    cors_allow_credentials: bool = Field(
        default=True, validation_alias="CORS_ALLOW_CREDENTIALS"
    )

    # ------------------------------------------------------------------
    # Supabase — Full suite (Auth + DB + Storage + Realtime)
    # ------------------------------------------------------------------
    supabase_url: str = Field(default="", validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", validation_alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(
        default="", validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )  # server-side admin — never expose to frontend

    # ------------------------------------------------------------------
    # Upstash Redis (TLS — rediss://)
    # ------------------------------------------------------------------
    redis_url: str = Field(
        default="", validation_alias="REDIS_URL"
    )  # e.g. rediss://:<password>@<host>:6380
    redis_max_connections: int = Field(
        default=20, validation_alias="REDIS_MAX_CONNECTIONS"
    )
    redis_default_ttl: int = Field(
        default=3600, validation_alias="REDIS_DEFAULT_TTL"
    )  # 1 hour in seconds

    # ------------------------------------------------------------------
    # Rate limiting defaults
    # ------------------------------------------------------------------
    rate_limit_requests: int = Field(
        default=100, validation_alias="RATE_LIMIT_REQUESTS"
    )
    rate_limit_window_seconds: int = Field(
        default=60, validation_alias="RATE_LIMIT_WINDOW_SECONDS"
    )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    # HMAC-SHA256 signing secret for opaque session tokens.
    # Minimum 32 random bytes (hex-encoded). NEVER expose to clients.
    session_secret: str = Field(default="", validation_alias="SESSION_SECRET")

    # AES-256-GCM encryption key for the per-session LLM API key blob.
    # Must be exactly 32 bytes when hex-decoded (i.e. 64 hex chars).
    key_encryption_secret: str = Field(
        default="", validation_alias="KEY_ENCRYPTION_SECRET"
    )

    # Session lifetime in seconds (sliding TTL refreshed on every activity).
    session_ttl: int = Field(default=7200, validation_alias="SESSION_TTL")

    # ------------------------------------------------------------------
    # WebSocket — Origin allowlist
    # Comma-separated list of allowed Origin header values for /ws/agent.
    # Intentionally separate from CORS_ORIGINS so staging can restrict WS
    # independently from REST. Must be set explicitly in env.
    # ------------------------------------------------------------------
    allowed_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        validation_alias="ALLOWED_ORIGINS",
    )

    # Rate limits specific to the WS/session layer
    ws_rate_limit_messages: int = Field(
        default=20, validation_alias="WS_RATE_LIMIT_MESSAGES"
    )  # chat_message frames per session per minute
    session_init_rate_limit: int = Field(
        default=10, validation_alias="SESSION_INIT_RATE_LIMIT"
    )  # POST /session/init per IP per minute

    # ------------------------------------------------------------------
    # LLM — Anthropic provider selection
    # Users supply their own API keys once via POST /session/llm-provider-key.
    # Keys are encrypted and stored in Redis for the session lifetime.
    # The only permanent server-side LLM credential is BEDROCK_API_KEY.
    # ------------------------------------------------------------------
    claude_provider: Literal["bedrock", "direct"] = Field(
        default="bedrock", validation_alias="CLAUDE_PROVIDER"
    )

    # Bedrock API key — server-managed, no IAM roles / secret keys needed
    bedrock_api_key: str = Field(default="", validation_alias="BEDROCK_API_KEY")
    bedrock_anthropic_model: str = Field(
        default="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        validation_alias="BEDROCK_ANTHROPIC_MODEL",
    )
    bedrock_region: str = Field(default="us-east-1", validation_alias="BEDROCK_REGION")
    # ------------------------------------------------------------------
    # Pydantic-settings — reads from .env + OS env vars
    # ------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,   # allow access by Python field name too
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    # (no list fields — nothing to validate here)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def cors_origins(self) -> list[str]:
        """Return CORS origins as a list, split from the raw comma-separated string."""
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        """Return WS-allowed Origins as a list (from ALLOWED_ORIGINS env var)."""
        return [o.strip() for o in self.allowed_origins_raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()