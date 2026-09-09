"""
app/services/llm_service.py
---------------------------
LangChain / LangGraph-ready LLM Service.

Architecture
────────────
- Designed for agentic systems built with LangChain and LangGraph.
- Accepts standard LangChain BaseMessage lists (SystemMessage, HumanMessage, AIMessage, ToolMessage).
- Auto-detects provider (OpenAI vs Anthropic) or accepts explicit provider override.
- Automatically resolves credentials per session:
    • Anthropic + Bedrock: uses server BEDROCK_API_KEY via boto3 Bearer token event injection.
    • Anthropic (direct): retrieves & decrypts session Anthropic API key in-memory.
    • OpenAI: retrieves & decrypts session OpenAI API key in-memory.
- Returns LangChain AIMessage with normalized .content and tool_calls.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

import boto3
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.exceptions import LLMException, LLMRateLimitException
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.session_service import SessionService

logger = get_logger(__name__)

# Model mapping dictionaries
_BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-4.5-sonnet": "global.anthropic.claude-haiku-4-5-20251001-v1:0",  # alias fallback
    "claude-4.5-haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0",    # alias fallback
}

_ANTHROPIC_DIRECT_MODEL_MAP: dict[str, str] = {
    "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku": "claude-3-5-haiku-20241022",
    "claude-3-7-sonnet": "claude-3-7-sonnet-20250219",
}


def _detect_provider(model: str) -> str:
    """Auto-detect provider from model identifier string."""
    m = model.lower()
    if m.startswith("claude") or m.startswith("anthropic") or "sonnet" in m or "haiku" in m or "opus" in m:
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("chatgpt") or "text-embedding" in m:
        return "openai"
    return "openai"


def _normalize_content(content: Any) -> str:
    """
    Normalise .content to a plain string.
    Bedrock Converse models sometimes return .content as a list of content-block
    dicts instead of a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                elif "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(json.dumps(block))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content) if content is not None else ""


class LLMService:
    """
    Per-session LLM client factory for LangChain and LangGraph agents.
    """

    def __init__(
        self,
        session_id: str | None = None,
        session_service: Optional["SessionService"] = None,
        api_key: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_service = session_service
        self._direct_api_key = api_key

    @classmethod
    def from_session(
        cls,
        session_id: str,
        session_service: "SessionService",
    ) -> "LLMService":
        """Factory for building an LLMService bound to a specific session."""
        return cls(session_id=session_id, session_service=session_service)

    def _get_bedrock_boto3_client(self) -> Any:
        """Create a boto3 bedrock-runtime client with injected Bearer token."""
        if not settings.bedrock_api_key:
            raise LLMException("BEDROCK_API_KEY is not configured on the server.")

        aws_kwargs: dict[str, Any] = {"region_name": settings.bedrock_region}

        client = boto3.client(service_name="bedrock-runtime", **aws_kwargs)

        bedrock_api_key = settings.bedrock_api_key

        def _inject_bearer_token(request: Any, **kwargs: Any) -> None:
            request.headers["Authorization"] = f"Bearer {bedrock_api_key}"

        client.meta.events.register(
            "before-send.bedrock-runtime.*",
            _inject_bearer_token,
        )
        return client

    async def _build_llm(
        self,
        provider: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> BaseChatModel:
        """Instantiate the appropriate LangChain BaseChatModel."""
        if provider == "openai":
            api_key = self._direct_api_key
            if not api_key and self.session_service and self.session_id:
                _, api_key = await self.session_service.get_api_key(
                    self.session_id, "openai"
                )

            if not api_key:
                raise LLMException(
                    "No OpenAI API Key found for this session. "
                    "Please submit your OpenAI key via POST /api/v1/session/llm-provider-key."
                )

            return ChatOpenAI(
                model=model,
                api_key=api_key,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        if provider == "anthropic":
            if settings.claude_provider == "bedrock":
                boto3_client = self._get_bedrock_boto3_client()
                bedrock_model = _BEDROCK_MODEL_MAP.get(model, model)
                if not bedrock_model.startswith("anthropic.") and not bedrock_model.startswith("us.anthropic."):
                    bedrock_model = settings.bedrock_anthropic_model

                return ChatBedrockConverse(
                    model=bedrock_model,
                    client=boto3_client,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            # Direct Anthropic
            api_key = self._direct_api_key
            if not api_key and self.session_service and self.session_id:
                _, api_key = await self.session_service.get_api_key(
                    self.session_id, "anthropic"
                )

            if not api_key:
                raise LLMException(
                    "No Anthropic API Key found for this session. "
                    "Please submit your Anthropic key via POST /api/v1/session/llm-provider-key."
                )

            direct_model = _ANTHROPIC_DIRECT_MODEL_MAP.get(model, model)
            return ChatAnthropic(
                model=direct_model,
                api_key=api_key,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        raise LLMException(f"Unsupported LLM provider: {provider!r}")

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        model: str,
        tools: Optional[list[Any]] = None,
        max_tokens: int = 8000,
        temperature: float = 0.7,
        request_type: str = "chat",
        provider: Optional[str] = None,
    ) -> AIMessage:
        """
        Call the underlying model and return a LangChain AIMessage.

        Args:
            messages:     LangChain message list (SystemMessage / HumanMessage / AIMessage / ToolMessage).
            model:        Model identifier string (e.g. 'claude-3-5-sonnet', 'gpt-4o', etc.).
            tools:        Optional list of tools / functions to bind to the model.
            max_tokens:   Maximum output tokens (default 8000).
            temperature:  Sampling temperature (default 0.7).
            request_type: Metadata tag for request purpose ("chat", "agent_step", etc.).
            provider:     Optional explicit provider override ("openai" | "anthropic").

        Returns:
            LangChain AIMessage with .content and .tool_calls populated.
        """
        actual_provider = provider or _detect_provider(model)
        logger.info(
            "llm_ainvoke_start",
            provider=actual_provider,
            model=model,
            request_type=request_type,
            session_id=self.session_id,
        )

        try:
            llm: BaseChatModel = await self._build_llm(
                actual_provider, model, max_tokens, temperature
            )

            if tools:
                llm = llm.bind_tools(tools)

            response: AIMessage = await llm.ainvoke(messages)  # type: ignore[assignment]

            # Flatten content when tools are not used so caller gets a consistent string
            if not tools:
                response.content = _normalize_content(response.content)

            return response

        except Exception as exc:
            err_str = str(exc)
            logger.warning(
                "llm_ainvoke_error",
                provider=actual_provider,
                model=model,
                error=err_str,
            )
            if "rate" in err_str.lower() or "throttl" in err_str.lower() or "429" in err_str:
                raise LLMRateLimitException(f"LLM Rate limit error: {exc}") from exc
            raise LLMException(f"LLM invocation error: {exc}") from exc
