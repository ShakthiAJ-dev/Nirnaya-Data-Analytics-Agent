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
     → Handles "ping" frame → replies with "pong" and slides session TTL
  5. On disconnect:
     → WSManager.cleanup(session_id)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_service import RedisService
from app.services.session_service import SessionService, verify_token
from app.services.ws_manager import WSManager

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
# Ping Handler
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
# Main receive loop
# ---------------------------------------------------------------------------

async def _receive_loop(
    ws: WebSocket,
    session_id: str,
    session_svc: SessionService,
    ws_manager: WSManager,
    redis_svc: RedisService,
) -> None:
    """
    Main WebSocket receive loop.
    Handles 'ping' frames to verify active connection.
    """
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
        transaction_id: str = msg.get("transactionId", "")

        if not request_type or not transaction_id:
            await _safe_send(
                ws,
                _make_frame(
                    "error",
                    transaction_id or "unknown",
                    content="Missing requestType or transactionId.",
                ),
            )
            continue

        # ── ping ──────────────────────────────────────────────────────────
        if request_type == "ping":
            task = asyncio.create_task(
                handle_ping(ws, transaction_id, session_id, session_svc, ws_manager)
            )
            ws_manager.register(session_id, transaction_id, task)
            continue

        # Unknown request type
        await _safe_send(
            ws,
            _make_frame(
                "error",
                transaction_id,
                content=f"Unknown requestType: {request_type!r}",
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
    # ── 1. Origin validation ────────────────────────────────────────────
    origin = ws.headers.get("origin", "")
    allowed = settings.allowed_origins
    if allowed and origin not in allowed:
        logger.warning("ws_origin_rejected", origin=origin)
        await ws.close(code=4403, reason="Origin not allowed")
        return

    # ── 2. Accept connection ────────────────────────────────────────────
    await ws.accept()

    # Pull services from app.state
    redis_svc: RedisService = ws.app.state.redis_service
    ws_manager: WSManager = ws.app.state.ws_manager
    session_svc = SessionService(redis_svc)

    # ── 3. Auth frame ───────────────────────────────────────────────────
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

    # ── 4. Receive loop ─────────────────────────────────────────────────
    try:
        await _receive_loop(ws, session_id, session_svc, ws_manager, redis_svc)
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.cleanup(session_id)
        logger.info("ws_disconnected", session_id=session_id)

