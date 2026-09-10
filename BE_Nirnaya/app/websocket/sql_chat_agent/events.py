"""
app/websocket/sql_chat_agent/events.py
----------------------------------------
Pure builder functions for WebSocket event shapes (server → client).

All functions return dicts — no I/O here. The caller is responsible for
serialising to JSON and sending over the WebSocket.

Event Types (server → client)
──────────────────────────────
  step       — one per discrete agent action; includes title + reasoning
  ask_user   — pauses graph; client must reply with ask_user_response
  final      — terminal event with markdown + artifact_ids + follow_ups

Event Types (client → server)  [parsed in ws_agent.py, not here]
──────────────────────────────
  ChatAgent          — new user turn
  ask_user_response  — answer to an ask_user event
  resume             — reconnect replay request
  ping               — keepalive
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Step names (canonical — FE uses these to render the right icon / label)
# ---------------------------------------------------------------------------

class StepName:
    LOADING_CONTEXT       = "loading_context"
    ANALYZING_QUESTION    = "analyzing_question"
    RUNNING_DISCOVERY     = "running_discovery"
    DECIDING              = "deciding"
    DISPATCHING_ARTIFACTS = "dispatching_artifacts"
    ARTIFACT_PROGRESS     = "artifact_progress"    # per-worker
    JOINING_RESULTS       = "joining_results"
    SYNTHESIZING          = "synthesizing"
    DIRECT_RESPONSE       = "direct_response"
    ERROR                 = "error"


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

def make_step(
    *,
    chat_id: str,
    turn_id: str,
    seq: int,
    name: str,
    status: str,                     # "in_progress" | "done" | "error"
    title: str,                      # Short human-readable label (e.g. "Analyzing Question")
    detail: str,                     # Longer description of what's happening
    reasoning: str = "",             # Why the agent is doing this (LLM-generated or static)
    artifact_id: str | None = None,  # Present for artifact_progress events
    worker_id: str | None = None,    # Present for per-worker events
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "step",
        "chat_id": chat_id,
        "turn_id": turn_id,
        "seq": seq,
        "name": name,
        "status": status,
        "title": title,
        "detail": detail,
        "reasoning": reasoning,
        "artifact_id": artifact_id,
        "worker_id": worker_id,
        "ts": _now(),
    }
    if extra:
        event.update(extra)
    return event


def make_ask_user(
    *,
    chat_id: str,
    turn_id: str,
    seq: int,
    question: str,
    mode: str,                      # "mcq" | "free_text"
    options: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "ask_user",
        "chat_id": chat_id,
        "turn_id": turn_id,
        "seq": seq,
        "question": question,
        "mode": mode,
        "options": options,
        "ts": _now(),
    }


def make_final(
    *,
    chat_id: str,
    turn_id: str,
    seq: int,
    markdown: str,
    artifact_ids: list[str],
    follow_up_questions: list[str],
) -> dict[str, Any]:
    return {
        "type": "final",
        "chat_id": chat_id,
        "turn_id": turn_id,
        "seq": seq,
        "markdown": markdown,
        "artifact_ids": artifact_ids,
        "follow_up_questions": follow_up_questions,
        "ts": _now(),
    }


def make_error(
    *,
    chat_id: str,
    turn_id: str,
    seq: int,
    message: str,
) -> dict[str, Any]:
    return {
        "type": "error",
        "chat_id": chat_id,
        "turn_id": turn_id,
        "seq": seq,
        "message": message,
        "ts": _now(),
    }


# ---------------------------------------------------------------------------
# Redis stream replay helpers
# ---------------------------------------------------------------------------

def stream_key(turn_id: str) -> str:
    """Redis key for the WS step-replay buffer."""
    return f"stream:{turn_id}"


STREAM_TTL_SECONDS = 1800  # 30 minutes — enough for reconnect window
