"""
app/websocket/sql_chat_agent/__init__.py
-----------------------------------------
Public entry point for the SQL chat agent package.
Import handle_chat_agent from here in ws_agent.py.
"""

from .entrypoint import handle_chat_agent

__all__ = ["handle_chat_agent"]
