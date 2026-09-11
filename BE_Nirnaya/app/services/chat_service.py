
"""
app/services/chat_service.py
-----------------------------
CRUD layer for the SQL agent data model:
  â€¢ chat_messages â€” one row per turn (question + answer) within a project
  â€¢ artifacts     â€” kpi / chart / table artifacts produced by workers

The old `chats` table has been removed. The chat_messages row UUID IS the
turn_id / chat_id used throughout the system. Turns are grouped by
`project_id` â€” the project IS the conversation container.

Table creation
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Call ChatService.initialize_chat_tables(supabase) once at startup
(idempotent â€” uses IF NOT EXISTS).

Design notes
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
- chat_messages.id = turn_id (server-generated); used as LangGraph checkpointer key.
- chat_messages.output is JSONB: {markdown, artifact_ids[], follow_up_questions[]}
  Written as NULL at turn start; updated when the graph completes.
- artifacts.result_data is capped at 1000 rows (enforced by sql_executor).
- session_id is the primary recovery key â€” all data for a session can be wiped atomically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import DatabaseException
from app.core.logging import get_logger
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

CHAT_MESSAGES_TABLE = "chat_messages"
ARTIFACTS_TABLE = "artifacts"

# ---------------------------------------------------------------------------
# DDL helpers â€” auto-created at startup
# ---------------------------------------------------------------------------

_CHAT_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   TEXT        NOT NULL,
    project_id   UUID        NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    database_id  UUID        REFERENCES public.databases(id) ON DELETE SET NULL,
    user_message TEXT        NOT NULL,
    output       JSONB,
    seq          BIGSERIAL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_project ON public.chat_messages (project_id, seq);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session  ON public.chat_messages (session_id);
"""

_ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS public.artifacts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    TEXT NOT NULL,
    database_id   UUID REFERENCES public.databases(id) ON DELETE CASCADE,
    project_id    UUID REFERENCES public.projects(id) ON DELETE CASCADE,
    message_id    UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS idx_artifacts_project    ON public.artifacts (project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_message    ON public.artifacts (message_id);
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
    CRUD operations for chat_messages and artifacts.
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
        Create chat_messages / artifacts tables if absent.
        Idempotent â€” safe to call on every startup.
        """
        for ddl in [_CHAT_MESSAGES_DDL, _ARTIFACTS_DDL]:
            try:
                await supabase.admin.rpc("exec_ddl", {"sql": ddl}).execute()
            except Exception as exc:
                err = str(exc).lower()
                if "pgrst202" in err or "could not find" in err:
                    logger.warning(
                        "exec_ddl_rpc_missing",
                        hint="exec_ddl RPC not found â€” create it in Supabase SQL editor first",
                    )
                    return
                logger.warning("chat_table_init_warning", error=str(exc))
        logger.info("chat_tables_ready")

    # ------------------------------------------------------------------
    # Turns  (one row per user turn + agent response)
    # ------------------------------------------------------------------

    async def create_turn(
        self,
        project_id: str,
        user_message: str,
        turn_id: str | None = None,
        database_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert a new turn row with output=NULL.
        The caller-supplied turn_id becomes the primary key and is used as
        the LangGraph checkpointer thread_id for interrupt/resume support.

        Returns the inserted row dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        row: dict[str, Any] = {
            "id":           turn_id or str(uuid.uuid4()),
            "session_id":   self._session_id,
            "project_id":   project_id,
            "user_message": user_message,
            "created_at":   now,
            "updated_at":   now,
        }
        if database_id:
            row["database_id"] = database_id
        try:
            resp = await self._supa.admin.table(CHAT_MESSAGES_TABLE).insert(row).execute()
            return resp.data[0] if resp.data else row
        except Exception as exc:
            raise DatabaseException(f"Failed to create turn: {exc}") from exc

    async def update_turn_output(
        self,
        turn_id: str,
        output: dict[str, Any],
    ) -> None:
        """
        Fill in the output JSONB column after the graph completes.
        output shape: {markdown, artifact_ids[], follow_up_questions[]}
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            await (
                self._supa.admin.table(CHAT_MESSAGES_TABLE)
                .update({"output": _make_json_safe(output), "updated_at": now})
                .eq("id", turn_id)
                .eq("session_id", self._session_id)
                .execute()
            )
        except Exception as exc:
            logger.warning("turn_output_update_failed", turn_id=turn_id, error=str(exc))

    async def get_recent_turns(
        self,
        project_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Return the N most recently *completed* turns for a project, oldest-first.
        Used to build the recent-conversation context injected into the LLM prompt.
        Incomplete turns (output IS NULL â€” still running) are excluded.
        """
        try:
            resp = (
                await self._supa.admin.table(CHAT_MESSAGES_TABLE)
                .select("id, user_message, output, seq, created_at")
                .eq("project_id", project_id)
                .eq("session_id", self._session_id)
                .not_.is_("output", "null")
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
        database_id: str | None,
        project_id: str,
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
        row: dict[str, Any] = {
            "id":            artifact_id,
            "session_id":    self._session_id,
            "project_id":    project_id,
            "message_id":    message_id,
            "type":          artifact_type,
            "title":         title,
            "sql_query":     sql_query,
            "config":        _make_json_safe(config),
            "result_data":   _make_json_safe(result_data),   # capped at â‰¤1000 rows by sql_executor
            "row_count":     row_count,
            "status":        status,
            "error_message": error_message,
            "created_at":    now,
            "updated_at":    now,
        }
        if database_id:
            row["database_id"] = database_id
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

    async def get_artifacts_batch(
        self,
        artifact_ids: list[str],
    ) -> list[dict[str, Any]]:
        """
        Fetch multiple artifacts by ID in a single query.
        Only returns artifacts owned by this session.
        Preserves the order of the requested IDs.
        """
        if not artifact_ids:
            return []
        try:
            resp = (
                await self._supa.admin.table(ARTIFACTS_TABLE)
                .select("*")
                .in_("id", artifact_ids)
                .eq("session_id", self._session_id)
                .execute()
            )
            rows_by_id = {r["id"]: r for r in (resp.data or [])}
            return [rows_by_id[aid] for aid in artifact_ids if aid in rows_by_id]
        except Exception as exc:
            logger.warning("artifacts_batch_fetch_failed", error=str(exc))
            return []

    async def mark_artifacts_stale(self, project_id: str) -> None:
        """
        Mark all 'fresh' artifacts in a project as 'stale'.
        Call when the user uploads new data or changes filters significantly.
        """
        try:
            await (
                self._supa.admin.table(ARTIFACTS_TABLE)
                .update({"status": "stale", "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("project_id", project_id)
                .eq("status", "fresh")
                .execute()
            )
        except Exception as exc:
            logger.warning("mark_stale_failed", project_id=project_id, error=str(exc))
