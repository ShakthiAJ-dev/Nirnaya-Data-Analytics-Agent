"""
app/services/checkpointer_service.py
-------------------------------------
LangGraph Postgres checkpointer — enables interrupt() / resume for the
ask_user flow and persists in-progress turn state across reconnects.

How it works
────────────
- Uses AsyncPostgresSaver from langgraph-checkpoint-postgres.
- setup() auto-creates required checkpoint tables on first run (idempotent).
- Keyed by thread_id = chat_id.
- After a turn completes, call delete_thread() to clean up.

Troubleshooting the connection error
──────────────────────────────────────
If you see: "failed to resolve host 'db.PROJECT.supabase.co'"

This is because `db.PROJECT.supabase.co` is the DIRECT PostgreSQL connection
which requires Supabase's IPv4 Add-On (~$4/mo) and may fail on some networks.

USE THE SESSION POOLER URL INSTEAD:
  Supabase → Settings → Database → Connection Pooling → Session mode → URI
  Format: postgresql://postgres.PROJECT:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres

Set it in .env as:
  DATABASE_URL=postgresql://postgres.tclffqikjmxkkdfvqsnq:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres

Note: Use port 5432 (Session mode), NOT 6543 (Transaction mode).
LangGraph checkpointer needs session mode for advisory locks.

No DATABASE_URL?
────────────────
If DATABASE_URL is empty, the checkpointer is disabled and the agent
falls back to in-memory state via MemorySaver. Interrupt/resume works
within the same server process lifetime (fine for v1 / dev).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# How long to wait for initial pool connections before giving up.
# Short timeout → fast startup even if DB is unreachable.
_POOL_OPEN_TIMEOUT_SECONDS = 5.0


class CheckpointerService:
    """
    Lifecycle-managed wrapper around AsyncPostgresSaver (or MemorySaver fallback).
    Attach one instance to app.state during lifespan startup.
    """

    def __init__(self) -> None:
        self._pool: Any = None
        self._checkpointer: Any = None
        self._enabled: bool = False

    async def initialize(self) -> None:
        """
        Attempt to initialise the Postgres checkpointer.

        Connection failure handling:
        - DNS failure / timeout → warn + fall back to MemorySaver
        - Missing DATABASE_URL → warn + fall back to MemorySaver
        - Auth failure → warn + fall back to MemorySaver

        In all fallback cases, interrupt()/resume STILL WORKS — state is kept
        in process memory (MemorySaver). It just won't survive a server restart.
        """
        if not settings.database_url:
            logger.warning(
                "checkpointer_disabled",
                reason="DATABASE_URL not set — using in-memory MemorySaver",
                hint=(
                    "Set DATABASE_URL to the Session Pooler URL from: "
                    "Supabase → Settings → Database → Connection Pooling → Session mode"
                ),
            )
            self._init_memory_saver()
            return

        try:
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            self._pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=5,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": None,
                    # TCP keepalive — keeps the connection alive through Supabase's
                    # idle-timeout and prevents "server closed the connection unexpectedly".
                    "keepalives": 1,
                    "keepalives_idle": 30,      # send first probe after 30s idle
                    "keepalives_interval": 10,  # probe every 10s after that
                    "keepalives_count": 5,      # drop after 5 failed probes
                },
                reconnect_timeout=3.0,
                reconnect_failed=self._on_reconnect_failed,
                # Actively validate connections before handing them out —
                # recycles any connection the DB server already closed.
                max_waiting=10,
                max_lifetime=300,   # retire connections after 5 min (before Supabase kills them)
                max_idle=60,        # close idle connections after 60s (psycopg-pool 3.1.x compatible)
            )

            # open(wait=True, timeout=N) waits at most N seconds for min_size
            # connections to become ready. If we can't connect, we fall back fast.
            await self._pool.open(wait=True, timeout=_POOL_OPEN_TIMEOUT_SECONDS)

            self._checkpointer = AsyncPostgresSaver(self._pool)
            await self._checkpointer.setup()  # creates checkpoint tables (idempotent)

            self._enabled = True
            logger.info("checkpointer_postgres_ready", min_pool=1, max_pool=5)

        except Exception as exc:
            err = str(exc).lower()
            if "resolve" in err or "dns" in err or "getaddrinfo" in err or "connection" in err:
                hint = (
                    "DNS/network failure. Use the SESSION POOLER URL, not the direct URL. "
                    "Find it at: Supabase → Settings → Database → Connection Pooling → "
                    "Session mode (port 5432). "
                    f"Format: postgresql://postgres.PROJECT:PW@aws-0-REGION.pooler.supabase.com:5432/postgres"
                )
            else:
                hint = "Check DATABASE_URL, Supabase password, and allow-list settings."

            logger.warning(
                "checkpointer_init_failed",
                error=str(exc)[:200],
                hint=hint,
            )
            # Close the pool if it was partially opened
            if self._pool:
                try:
                    await self._pool.close()
                except Exception:
                    pass
                self._pool = None

            self._init_memory_saver()

    def _init_memory_saver(self) -> None:
        """Fall back to in-memory checkpointer (works within single process)."""
        try:
            from langgraph.checkpoint.memory import MemorySaver
            self._checkpointer = MemorySaver()
            self._enabled = True  # still enabled — just in-memory
            logger.info(
                "checkpointer_memory_saver_active",
                note="Interrupt/resume works but state is lost on server restart",
            )
        except Exception as exc:
            logger.warning("checkpointer_memory_saver_failed", error=str(exc))
            self._enabled = False

    @staticmethod
    def _on_reconnect_failed(pool: Any) -> None:
        """Called by psycopg_pool when a reconnect attempt fails. Suppress per-attempt noise."""
        pass  # We log once at the top level; suppress per-attempt pool warnings

    async def close(self) -> None:
        """Graceful shutdown — close pool connections."""
        if self._pool:
            try:
                await self._pool.close()
                logger.info("checkpointer_pool_closed")
            except Exception:
                pass

    @property
    def checkpointer(self) -> Any | None:
        """Returns AsyncPostgresSaver or MemorySaver; None only if both failed."""
        return self._checkpointer if self._enabled else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def delete_thread(self, thread_id: str) -> None:
        """
        Delete checkpoint state for a completed turn.
        No-op for MemorySaver (it manages memory itself).
        """
        if not self._enabled or not self._checkpointer:
            return
        # Only Postgres checkpointer has adelete
        if self._pool is None:
            return
        try:
            await self._checkpointer.adelete({"configurable": {"thread_id": thread_id}})
        except Exception as exc:
            logger.debug("checkpoint_delete_failed", thread_id=thread_id, error=str(exc))
