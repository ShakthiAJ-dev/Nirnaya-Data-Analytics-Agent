"""
app/websocket
-------------
WebSocket route handlers and endpoints.
"""

from app.websocket.ws_agent import router as ws_agent_router

__all__ = ["ws_agent_router"]
