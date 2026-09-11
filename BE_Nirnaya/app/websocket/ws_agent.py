"""
app/websocket/ws_agent.py
-------------------------
WebSocket endpoint: /ws/agent

Lifecycle
─────────
  1. accept()
  2. Validate Origin header against ALLOWED_ORIGINS → close(4403) on fail
  3. Wait for first frame: {"type": "auth", "token": "..."}
     → Validate token + look up session in Redis
     → On failure: close(4001, "invalid or expired session")
     → On success: enter receive loop
  4. Receive loop:
     → "ping"              → pong + slide session TTL
     → "ChatAgent"         → spawn handle_chat_agent task
     → "ask_user_response" → resume an interrupted graph turn
     → "resume"            → replay Redis stream events (reconnect)
     → unknown             → send error frame
  5. On disconnect:
     → WSManager.cleanup(session_id)

Message shapes (client → server)
──────────────────────────────────
  Auth frame (first):
    { "type": "auth", "token": "..." }

  New chat turn (first message — no chat_id needed):
    {
      "requestType": "ChatAgent",
      "transactionId": "uuid",
      "project_id": "uuid",
      "text": "What is total revenue by country?"
    }

  Subsequent turn in same chat:
    {
      "requestType": "ChatAgent",
      "transactionId": "uuid",
      "project_id": "uuid",
      "chat_id": "uuid",
      "text": "Break that down by product category too"
    }

  Clarification answer (after ask_user event):
    {
      "requestType": "ask_user_response",
      "transactionId": "uuid",
      "turn_id": "uuid",
      "answer": "Monthly, USD only"
    }

  Reconnect replay:
    {
      "requestType": "resume",
      "transactionId": "uuid",
      "turn_id": "uuid",
      "last_seq": 6
    }

  Keepalive:
    { "requestType": "ping", "transactionId": "uuid" }
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_service import RedisService
from app.services.session_service import SessionService, verify_token
from app.services.ws_manager import WSManager
from app.websocket.sql_chat_agent.entrypoint import (
    handle_ask_user_response,
    handle_chat_agent,
)
from app.websocket.sql_chat_agent.events import stream_key

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(
    msg_type: str,
    transaction_id: str,
    content: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    frame: dict[str, Any] = {
        "type": msg_type,
        "transactionId": transaction_id,
        "content": content,
        "timestamp": int(time.time()),
    }
    if extra:
        frame.update(extra)
    return json.dumps(frame)


async def _safe_send(ws: WebSocket, text: str) -> None:
    """Send a text frame; swallow errors if the socket is already closed."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_text(text)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Handler: ping
# ---------------------------------------------------------------------------

async def handle_ping(
    ws: WebSocket,
    transaction_id: str,
    session_id: str,
    session_svc: SessionService,
    ws_manager: WSManager,
) -> None:
    """Slide session TTL and respond with pong."""
    try:
        await session_svc.refresh_session(session_id)
        await _safe_send(ws, _make_frame("pong", transaction_id))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _safe_send(ws, _make_frame("error", transaction_id, content=str(exc)))
    finally:
        ws_manager.remove_task(session_id, transaction_id)


# ---------------------------------------------------------------------------
# Handler: ChatAgent — new analytics turn
# ---------------------------------------------------------------------------

async def handle_chat_agent_frame(
    ws: WebSocket,
    msg: dict[str, Any],
    session_id: str,
    ws_manager: WSManager,
    supabase_service: Any,
    redis_service: RedisService,
    checkpointer: Any,
) -> None:
    """
    Spawn an async task that runs the full orchestrator graph for this turn.
    """
    transaction_id: str  = msg.get("transactionId", str(uuid.uuid4()))
    project_id: str      = msg.get("project_id", "")
    # chat_id is OPTIONAL — if absent the server generates one (new conversation).
    # The FE receives the generated chat_id in the ack and sends it back on
    # subsequent turns to continue the same conversation.
    chat_id: str         = msg.get("chat_id", "") or str(uuid.uuid4())
    user_message: str    = msg.get("text", "").strip()
    turn_id: str         = str(uuid.uuid4())
    # Model params — FE selects, defaults to Haiku if not specified
    model: str           = msg.get("model", "claude-4.5-haiku")
    provider: str | None = msg.get("provider")  # None → LLMService auto-detects

    if not project_id or not user_message:
        await _safe_send(
            ws,
            _make_frame(
                "error",
                transaction_id,
                content="ChatAgent frame requires: project_id, text",
            ),
        )
        return

    async def _ws_send_raw(payload: str) -> None:
        await _safe_send(ws, payload)

    async def _run_agent() -> None:
        try:
            await handle_chat_agent(
                session_id=session_id,
                project_id=project_id,
                chat_id=chat_id,
                user_message=user_message,
                turn_id=turn_id,
                model=model,
                provider=provider,
                ws_send_raw=_ws_send_raw,
                supabase_service=supabase_service,
                redis_service=redis_service,
                checkpointer=checkpointer,
            )
        except asyncio.CancelledError:
            logger.info("chat_agent_task_cancelled", turn_id=turn_id)
        except Exception as exc:
            logger.error("chat_agent_unhandled_error", turn_id=turn_id, error=str(exc))
            await _safe_send(
                ws,
                json.dumps({
                    "type": "error",
                    "turn_id": turn_id,
                    "message": f"Unexpected error: {str(exc)[:200]}",
                }),
            )
        finally:
            ws_manager.remove_task(session_id, transaction_id)

    task = asyncio.create_task(_run_agent())
    ws_manager.register(session_id, transaction_id, task)

    # Acknowledge immediately so FE knows the turn started.
    # chat_id is included so FE can store it and reuse it on the next turn.
    await _safe_send(
        ws,
        _make_frame(
            "ack",
            transaction_id,
            content="Turn started",
            extra={"turn_id": turn_id, "chat_id": chat_id, "project_id": project_id},
        ),
    )


# ---------------------------------------------------------------------------
# Handler: ask_user_response
# ---------------------------------------------------------------------------

async def handle_ask_user_response_frame(
    ws: WebSocket,
    msg: dict[str, Any],
    session_id: str,
    ws_manager: WSManager,
    supabase_service: Any,
    redis_service: RedisService,
    checkpointer: Any,
) -> None:
    transaction_id: str  = msg.get("transactionId", str(uuid.uuid4()))
    turn_id: str         = msg.get("turn_id", "")
    answer: str          = msg.get("answer", "")
    model: str           = msg.get("model", "claude-4.5-haiku")
    provider: str | None = msg.get("provider")

    if not turn_id:
        await _safe_send(ws, _make_frame("error", transaction_id, content="ask_user_response requires turn_id"))
        return

    async def _ws_send_raw(payload: str) -> None:
        await _safe_send(ws, payload)

    async def _resume() -> None:
        try:
            await handle_ask_user_response(
                session_id=session_id,
                turn_id=turn_id,
                answer=answer,
                model=model,
                provider=provider,
                ws_send_raw=_ws_send_raw,
                supabase_service=supabase_service,
                redis_service=redis_service,
                checkpointer=checkpointer,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("ask_user_resume_unhandled", turn_id=turn_id, error=str(exc))
        finally:
            ws_manager.remove_task(session_id, transaction_id)

    task = asyncio.create_task(_resume())
    ws_manager.register(session_id, transaction_id, task)


# ---------------------------------------------------------------------------
# Handler: resume (reconnect replay)
# ---------------------------------------------------------------------------

async def handle_resume_frame(
    ws: WebSocket,
    msg: dict[str, Any],
    redis_service: RedisService,
) -> None:
    """
    Replay buffered step events from Redis stream for seq > last_seq.
    """
    turn_id: str = msg.get("turn_id", "")
    last_seq: int = int(msg.get("last_seq", -1))

    if not turn_id:
        return

    key = stream_key(turn_id)
    try:
        raw_events: list[str] = await redis_service.client.lrange(key, 0, -1)
    except Exception:
        return

    for raw in raw_events:
        try:
            event = json.loads(raw)
            if event.get("seq", -1) > last_seq:
                await _safe_send(ws, raw)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Main receive loop
# ---------------------------------------------------------------------------

async def _receive_loop(
    ws: WebSocket,
    session_id: str,
    session_svc: SessionService,
    ws_manager: WSManager,
    redis_service: RedisService,
    supabase_service: Any,
    checkpointer: Any,
) -> None:
    while True:
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            break
        except Exception:
            break

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue  # malformed — ignore

        request_type: str = msg.get("requestType", "")
        # transactionId is optional — server generates one if FE omits it.
        # Used for task registration/cancellation and ack correlation only.
        transaction_id: str = msg.get("transactionId", "") or str(uuid.uuid4())

        if not request_type:
            await _safe_send(
                ws,
                _make_frame(
                    "error",
                    transaction_id,
                    content="Missing requestType.",
                ),
            )
            continue

        # ── ping ──────────────────────────────────────────────────────
        if request_type == "ping":
            task = asyncio.create_task(
                handle_ping(ws, transaction_id, session_id, session_svc, ws_manager)
            )
            ws_manager.register(session_id, transaction_id, task)
            continue

        # ── ChatAgent — new analytics turn ────────────────────────────
        if request_type == "ChatAgent":
            await handle_chat_agent_frame(
                ws=ws,
                msg=msg,
                session_id=session_id,
                ws_manager=ws_manager,
                supabase_service=supabase_service,
                redis_service=redis_service,
                checkpointer=checkpointer,
            )
            continue

        # ── ask_user_response — resume interrupted graph ───────────────
        if request_type == "ask_user_response":
            await handle_ask_user_response_frame(
                ws=ws,
                msg=msg,
                session_id=session_id,
                ws_manager=ws_manager,
                supabase_service=supabase_service,
                redis_service=redis_service,
                checkpointer=checkpointer,
            )
            continue

        # ── resume — reconnect replay ──────────────────────────────────
        if request_type == "resume":
            task = asyncio.create_task(handle_resume_frame(ws, msg, redis_service))
            ws_manager.register(session_id, transaction_id, task)
            continue

        # ── Unknown request type ───────────────────────────────────────
        await _safe_send(
            ws,
            _make_frame(
                "error",
                transaction_id,
                content=f"Unknown requestType: {request_type!r}. "
                        "Valid types: ping, ChatAgent, ask_user_response, resume",
            ),
        )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/agent")
async def ws_agent(ws: WebSocket) -> None:
    """
    Redis-managed WebSocket agent endpoint.

    Accepts connections only from ALLOWED_ORIGINS.
    Auth is performed via the first message frame: {"type": "auth", "token": "..."}
    """
    # ── 1. Origin validation ────────────────────────────────────────
    origin = ws.headers.get("origin", "")
    allowed = settings.allowed_origins
    if allowed and origin not in allowed:
        logger.warning("ws_origin_rejected", origin=origin)
        await ws.close(code=4403, reason="Origin not allowed")
        return

    # ── 2. Accept connection ────────────────────────────────────────
    await ws.accept()

    # Pull services from app.state
    redis_svc: RedisService = ws.app.state.redis_service
    supabase_svc = ws.app.state.supabase_service
    ws_manager: WSManager = ws.app.state.ws_manager
    checkpointer_svc = getattr(ws.app.state, "checkpointer_service", None)
    checkpointer = checkpointer_svc.checkpointer if checkpointer_svc else None
    session_svc = SessionService(redis_svc)

    # ── 3. Auth frame ───────────────────────────────────────────────
    try:
        raw_auth = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4001, reason="Auth timeout — send auth frame within 10s")
        return
    except WebSocketDisconnect:
        return

    try:
        auth_msg = json.loads(raw_auth)
    except json.JSONDecodeError:
        await ws.close(code=4001, reason="Invalid auth frame — expected JSON")
        return

    if auth_msg.get("type") != "auth" or not auth_msg.get("token"):
        await ws.close(code=4001, reason="First frame must be {type: 'auth', token: '...'}")
        return

    token: str = auth_msg["token"]
    session_id = verify_token(token)
    if session_id is None:
        await ws.close(code=4001, reason="invalid or expired session")
        return

    # Confirm session exists in Redis
    session_data = await session_svc.get_session(session_id)
    if session_data is None:
        await ws.close(code=4001, reason="invalid or expired session")
        return

    logger.info("ws_auth_success", session_id=session_id, origin=origin)

    # Slide TTL on connect
    await session_svc.refresh_session(session_id)

    # ── 4. Receive loop ─────────────────────────────────────────────
    try:
        await _receive_loop(
            ws=ws,
            session_id=session_id,
            session_svc=session_svc,
            ws_manager=ws_manager,
            redis_service=redis_svc,
            supabase_service=supabase_svc,
            checkpointer=checkpointer,
        )
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.cleanup(session_id)
        logger.info("ws_disconnected", session_id=session_id)
