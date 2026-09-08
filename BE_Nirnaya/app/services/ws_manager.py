"""
app/services/ws_manager.py
---------------------------
In-process WebSocket task registry.

Tracks per-session asyncio.Task objects so WS message handlers can:
  - Cancel an in-flight chat_message task via a 'cancel' frame.
  - Clean up all tasks on disconnect.

This state is intentionally NOT in Redis — asyncio.Task objects are
process-bound. If you scale to multiple Render instances, each connection
is pinned to one instance so the local registry is always authoritative
for that socket.

Usage:
    manager = WSManager()              # one singleton on app.state
    manager.register(sid, txn, task)   # when spawning a task
    manager.cancel(sid, txn)           # from the 'cancel' handler
    manager.cleanup(sid)               # on socket disconnect
"""

from __future__ import annotations

import asyncio
from typing import Dict

from app.core.logging import get_logger

logger = get_logger(__name__)

# session_id → {transaction_id → Task}
_Registry = Dict[str, Dict[str, asyncio.Task]]  # type: ignore[type-arg]


class WSManager:
    """Singleton task registry.  Attach to app.state in lifespan."""

    def __init__(self) -> None:
        self._tasks: _Registry = {}

    # ------------------------------------------------------------------
    # Task registration
    # ------------------------------------------------------------------

    def register(self, session_id: str, transaction_id: str, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        """Register a running task. Overwrites any previous task with the same IDs."""
        if session_id not in self._tasks:
            self._tasks[session_id] = {}
        self._tasks[session_id][transaction_id] = task
        logger.debug(
            "ws_task_registered",
            session_id=session_id,
            transaction_id=transaction_id,
        )

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel(self, session_id: str, transaction_id: str) -> bool:
        """
        Cancel the task identified by (session_id, transaction_id).
        Returns True if a task was found and cancelled, False otherwise.
        """
        task = self._tasks.get(session_id, {}).get(transaction_id)
        if task is None or task.done():
            return False
        task.cancel()
        logger.info(
            "ws_task_cancelled",
            session_id=session_id,
            transaction_id=transaction_id,
        )
        return True

    def cancel_all(self, session_id: str) -> int:
        """Cancel all running tasks for a session. Returns count cancelled."""
        tasks = self._tasks.get(session_id, {})
        count = 0
        for txn_id, task in list(tasks.items()):
            if not task.done():
                task.cancel()
                count += 1
                logger.debug(
                    "ws_task_cancelled_on_cleanup",
                    session_id=session_id,
                    transaction_id=txn_id,
                )
        return count

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self, session_id: str) -> None:
        """
        Remove all task tracking for a session.
        Called on socket disconnect — does NOT touch Redis session/history.
        """
        n = self.cancel_all(session_id)
        self._tasks.pop(session_id, None)
        logger.info("ws_session_cleaned_up", session_id=session_id, tasks_cancelled=n)

    def remove_task(self, session_id: str, transaction_id: str) -> None:
        """Remove a single completed task from the registry."""
        self._tasks.get(session_id, {}).pop(transaction_id, None)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def active_session_count(self) -> int:
        return len(self._tasks)

    @property
    def active_task_count(self) -> int:
        return sum(
            1
            for tasks in self._tasks.values()
            for t in tasks.values()
            if not t.done()
        )