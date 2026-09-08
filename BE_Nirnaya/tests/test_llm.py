"""
tests/test_llm.py
-----------------
Quick smoke-test for LLMService.

Run with:
    cd BE_Nirnaya
    python -m tests.test_llm

Set your keys either in .env or as environment variables:
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.llm_service import LLMService, Message


# ── Fill in your keys here for a quick one-off test, OR keep as None to ──
# ── fall through to the environment variable loaded by settings          ──
OPENAI_KEY = os.getenv("OPENAI_API_KEY")        # e.g. "sk-..."
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")  # e.g. "sk-ant-..."


# async def test_openai() -> None:
#     if not OPENAI_KEY:
#         print("⚠  OPENAI_API_KEY not set — skipping OpenAI test.\n")
#         return

#     print("── OpenAI (gpt-4o) ─────────────────────────────────────────────")
#     client = LLMService.create(provider="openai", api_key=OPENAI_KEY)

#     # Single completion
#     response = await client.complete(
#         [Message(role="user", content="Say hello in one sentence.")],
#         max_tokens=50,
#     )
#     print(f"complete → {response.content}")
#     print(f"  model={response.model}  tokens={response.input_tokens}+{response.output_tokens}  latency={response.latency_ms:.0f}ms\n")

#     # Streaming
#     print("stream  → ", end="", flush=True)
#     async for chunk in client.stream(
#         [Message(role="user", content="Count to 5, one number per word.")],
#         max_tokens=30,
#     ):
#         print(chunk, end="", flush=True)
#     print("\n")


async def test_anthropic() -> None:
    print("── Anthropic (claude-3-5-sonnet) ────────────────────────────────")
    client = LLMService.create(provider="anthropic")

    # Single completion
    response = await client.complete(
        [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Say hello in one sentence."),
        ],
        max_tokens=50,
    )
    print(f"complete → {response.content}")
    print(f"  model={response.model}  tokens={response.input_tokens}+{response.output_tokens}  latency={response.latency_ms:.0f}ms\n")

    # Streaming
    print("stream  → ", end="", flush=True)
    async for chunk in client.stream(
        [Message(role="user", content="Count to 5, one number per word.")],
        max_tokens=30,
    ):
        print(chunk, end="", flush=True)
    print("\n")


async def main() -> None:
    # await test_openai()
    await test_anthropic()
    print("✓ LLMService tests complete.")


if __name__ == "__main__":
    asyncio.run(main())
