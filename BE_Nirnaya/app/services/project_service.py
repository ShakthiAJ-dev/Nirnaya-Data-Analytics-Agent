"""
app/services/project_service.py
--------------------------------
Project CRUD — each project is a chat scoped to session_id.
Stored in public.projects (see ProjectRecord in data_models.py).
Title starts as 'Untitled'; updated when user asks first question.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import DatabaseException, NotFoundException
from app.core.logging import get_logger
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)
TABLE = "projects"


class ProjectService:
    def __init__(self, session_id: str, supabase: SupabaseService) -> None:
        self._session_id = session_id
        self._supa = supabase

    async def create(self, database_id: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "session_id": self._session_id,
            "title": "Untitled",
            "created_at": now,
            "updated_at": now,
        }
        if database_id:
            payload["database_id"] = database_id
        try:
            resp = await self._supa.admin.table(TABLE).insert(payload).execute()
            if not resp.data:
                raise DatabaseException("Create project returned no data.")
            logger.info("project_created", session_id=self._session_id)
            return resp.data[0]
        except DatabaseException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Create project failed: {exc}") from exc

    async def list(self) -> list[dict[str, Any]]:
        try:
            resp = await (
                self._supa.admin.table(TABLE)
                .select("*")
                .eq("session_id", self._session_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            raise DatabaseException(f"List projects failed: {exc}") from exc

    async def get(self, project_id: str) -> dict[str, Any]:
        try:
            resp = await (
                self._supa.admin.table(TABLE)
                .select("*")
                .eq("id", project_id)
                .eq("session_id", self._session_id)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                raise NotFoundException(f"Project {project_id!r} not found.")
            return rows[0]
        except NotFoundException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Get project failed: {exc}") from exc

    async def update_title(self, project_id: str, title: str) -> dict[str, Any]:
        await self.get(project_id)  # ownership check
        try:
            now = datetime.now(timezone.utc).isoformat()
            resp = await (
                self._supa.admin.table(TABLE)
                .update({"title": title, "updated_at": now})
                .eq("id", project_id)
                .eq("session_id", self._session_id)
                .execute()
            )
            if not resp.data:
                raise DatabaseException("Update title returned no data.")
            return resp.data[0]
        except DatabaseException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Update title failed: {exc}") from exc

    async def delete(self, project_id: str) -> None:
        await self.get(project_id)  # ownership check
        try:
            await (
                self._supa.admin.table(TABLE)
                .delete()
                .eq("id", project_id)
                .eq("session_id", self._session_id)
                .execute()
            )
            logger.info("project_deleted", project_id=project_id, session_id=self._session_id)
        except Exception as exc:
            raise DatabaseException(f"Delete project failed: {exc}") from exc
