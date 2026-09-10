
"""
app/services/chat_service.py
-----------------------------
CRUD layer for the chat data model introduced by the SQL agent:
  • chats         — one row per conversation within a database
  • chat_messages — messages (user + assistant) within a chat
  • artifacts     — kpi / chart / table artifacts produced by workers

Table creation
──────────────
Call ChatService.initialize_chat_tables(supabase) once at startup






(idempotent — uses IF NOT EXISTS).

Design notes
────────────
- chat_messages.content is JSONB: { markdown, steps[], artifact_ids[], follow_up_questions[] }
  No full result_data ever lives here — artifacts own that.
- artifacts.result_data is capped at 1000 rows (enforced by sql_executor).
- session_id is the primary recovery key for both artifacts and chats —
  all data for a session can be wiped atomically.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import DatabaseException
from app.core.logging import get_logger
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

CHATS_TABLE = "chats"
CHAT_MESSAGES_TABLE = "chat_messages"
ARTIFACTS_TABLE = "artifacts"

# ---------------------------------------------------------------------------
# DDL helpers — auto-created at startup
# ---------------------------------------------------------------------------

_CHATS_DDL = """
CREATE TABLE IF NOT EXISTS public.chats (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  TEXT  NOT NULL,
    project_id  UUID  REFERENCES public.projects(id) ON DELETE CASCADE,
    database_id UUID  REFERENCES public.databases(id) ON DELETE CASCADE,
    title       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chats_session_id ON public.chats (session_id);
CREATE INDEX IF NOT EXISTS idx_chats_project_id ON public.chats (project_id);
"""

_CHAT_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id       UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id  UUID    NOT NULL REFERENCES public.chats(id) ON DELETE CASCADE,
    role     TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content  JSONB   NOT NULL DEFAULT '{}',
    seq      BIGSERIAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_seq ON public.chat_messages (chat_id, seq);
"""

_ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS public.artifacts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    TEXT NOT NULL,
    database_id   UUID REFERENCES public.databases(id) ON DELETE CASCADE,
    chat_id       UUID REFERENCES public.chats(id),
    message_id    UUID REFERENCES public.chat_messages(id),
    type          TEXT NOT NULL CHECK (type IN ('kpi', 'chart', 'table')),
    title         TEXT NOT NULL,
    sql_query     TEXT NOT NULL,
    config        JSONB NOT NULL DEFAULT '{}',
    result_data   JSONB NOT NULL DEFAULT '[]',
    row_count     INT  NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'fresh' CHECK (status IN ('fresh', 'stale', 'error')),
    error_message TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session_db ON public.artifacts (session_id, database_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_chat ON public.artifacts (chat_id);
"""


def _make_json_safe(obj: Any) -> Any:
    """Recursively ensure obj consists only of standard JSON-serializable types."""
    if hasattr(obj, "model_dump"):
        return _make_json_safe(obj.model_dump())
    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        return _make_json_safe(obj.dict())
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    return obj


class ChatService:
    """
    CRUD operations for chats, chat_messages, and artifacts.
    Pass session_id so every write is scoped to the session.
    """

    def __init__(self, session_id: str, supabase: SupabaseService) -> None:
        self._session_id = session_id
        self._supa = supabase

    # ------------------------------------------------------------------
    # One-time table initialisation (called at startup)
    # ------------------------------------------------------------------

    @staticmethod
    async def initialize_chat_tables(supabase: SupabaseService) -> None:
        """
        Create chats / chat_messages / artifacts tables if absent.
        Idempotent — safe to call on every startup.
        """
        for ddl in [_CHATS_DDL, _CHAT_MESSAGES_DDL, _ARTIFACTS_DDL]:
            try:
                await supabase.admin.rpc("exec_ddl", {"sql": ddl}).execute()
            except Exception as exc:
                err = str(exc).lower()
                if "pgrst202" in err or "could not find" in err:
                    logger.warning(
                        "exec_ddl_rpc_missing",
                        hint="exec_ddl RPC not found — create it in Supabase SQL editor first",
                    )
                    return
                logger.warning("chat_table_init_warning", error=str(exc))
        logger.info("chat_tables_ready")

    # ------------------------------------------------------------------
    # Chats
    # ------------------------------------------------------------------

    async def create_chat(
        self,
        database_id: str,
        project_id: str | None = None,
        title: str | None = None,
        chat_id: str | None = None,  # Accept caller-supplied UUID (e.g. server-generated)
    ) -> dict[str, Any]:
        """Create a new chat row; returns the full row dict."""
        row: dict[str, Any] = {
            "id": chat_id or str(uuid.uuid4()),
            "session_id": self._session_id,
            "database_id": database_id,
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if project_id:
            row["project_id"] = project_id
        try:
            resp = await self._supa.admin.table(CHATS_TABLE).insert(row).execute()
            return resp.data[0] if resp.data else row
        except Exception as exc:
            raise DatabaseException(f"Failed to create chat: {exc}") from exc

    async def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        try:
            resp = (
                await self._supa.admin.table(CHATS_TABLE)
                .select("*")
                .eq("id", chat_id)
                .eq("session_id", self._session_id)
                .maybe_single()
                .execute()
            )
            return resp.data
        except Exception:
            return None

    async def update_chat_title(self, chat_id: str, title: str) -> None:
        try:
            await (
                self._supa.admin.table(CHATS_TABLE)
                .update({"title": title, "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", chat_id)
                .eq("session_id", self._session_id)
                .execute()
            )
        except Exception as exc:
            logger.warning("chat_title_update_failed", chat_id=chat_id, error=str(exc))

    async def list_chats(self, database_id: str) -> list[dict[str, Any]]:
        try:
            resp = (
                await self._supa.admin.table(CHATS_TABLE)
                .select("*")
                .eq("session_id", self._session_id)
                .eq("database_id", database_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Chat messages
    # ------------------------------------------------------------------

    async def add_message(
        self,
        chat_id: str,
        role: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist one message (user or assistant).

        content shape for 'assistant':
        {
          "markdown": "...",
          "steps": [...],          # static step log (not for replay)
          "artifact_ids": [...],
          "follow_up_questions": [...]
        }
        """
        row = {
            "id": str(uuid.uuid4()),
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = await self._supa.admin.table(CHAT_MESSAGES_TABLE).insert(row).execute()
            return resp.data[0] if resp.data else row
        except Exception as exc:
            raise DatabaseException(f"Failed to add message: {exc}") from exc

    async def get_recent_messages(
        self,
        chat_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the N most recent messages, oldest-first (for prompt context)."""
        try:
            resp = (
                await self._supa.admin.table(CHAT_MESSAGES_TABLE)
                .select("id, role, content, seq, created_at")
                .eq("chat_id", chat_id)
                .order("seq", desc=True)
                .limit(limit)
                .execute()
            )
            rows = resp.data or []
            return list(reversed(rows))  # restore chronological order
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    async def create_artifact(
        self,
        *,
        database_id: str,
        chat_id: str,
        message_id: str | None,
        artifact_type: str,
        title: str,
        sql_query: str,
        config: dict[str, Any],
        result_data: list[dict[str, Any]],
        row_count: int,
        status: str = "fresh",
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Write a fully-resolved artifact row to Postgres. Returns the row."""
        artifact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": artifact_id,
            "session_id": self._session_id,
            "database_id": database_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "type": artifact_type,
            "title": title,
            "sql_query": sql_query,
            "config": _make_json_safe(config),
            "result_data": _make_json_safe(result_data),      # already capped at <=1000 rows
            "row_count": row_count,
            "status": status,
            "error_message": error_message,
            "created_at": now,
            "updated_at": now,
        }
        try:
            resp = await self._supa.admin.table(ARTIFACTS_TABLE).insert(row).execute()
            return resp.data[0] if resp.data else row
        except Exception as exc:
            raise DatabaseException(f"Failed to create artifact: {exc}") from exc

    async def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        try:
            resp = (
                await self._supa.admin.table(ARTIFACTS_TABLE)
                .select("*")
                .eq("id", artifact_id)
                .eq("session_id", self._session_id)
                .maybe_single()
                .execute()
            )
            return resp.data
        except Exception:
            return None

    async def mark_artifacts_stale(self, chat_id: str) -> None:
        """
        Mark all 'fresh' artifacts in a chat as 'stale'.
        Call when the user uploads new data or changes filters significantly.
        """
        try:
            await (
                self._supa.admin.table(ARTIFACTS_TABLE)
                .update({"status": "stale", "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("chat_id", chat_id)
                .eq("status", "fresh")
                .execute()
            )
        except Exception as exc:
            logger.warning("mark_stale_failed", chat_id=chat_id, error=str(exc))
