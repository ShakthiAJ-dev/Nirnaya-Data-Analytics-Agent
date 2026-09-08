"""
app/services/data_service/__init__.py
--------------------------------------
DataService — the unified session-scoped data access layer.

Provides access to both:
  • TableService  — Supabase PostgreSQL (PostgREST) CRUD
  • FileService   — Supabase Storage (bucket) operations

Usage
─────
Instantiate once per request using the session_id:

    from app.services.data_service import DataService

    ds = DataService(
        session_id=session_id,
        supabase=supabase_service,   # from app.state
    )

    # --- Table operations ---
    await ds.table.ensure_table("chat_history")         # idempotent DDL
    row = await ds.table.insert("chat_history", {
        "role": "user",
        "content": "Hello, Nirnaya!",
    })
    history = await ds.table.get_chat_history()

    # --- File operations ---
    path = await ds.file.upload("uploads/data.csv", csv_bytes)
    data = await ds.file.download("uploads/data.csv")
    files = await ds.file.list_files()

Design
──────
• session_id is the partition key for both services.
  - Tables  : every row has session_id, every query filters by it.
  - Storage : every path is prefixed with session_id/.
• DataService is a thin factory / façade — the actual work is
  delegated to TableService and FileService.
• Instantiate DataService per-request (not as a singleton) because
  each request has a specific session_id.

FastAPI integration example
────────────────────────────
    async def my_route(request: Request, redis: RedisDep) -> ...:
        session_id, svc = await _require_session(request, redis)
        ds = DataService(
            session_id=session_id,
            supabase=request.app.state.supabase_service,
        )
        # use ds.table / ds.file ...
"""

from __future__ import annotations

from app.services.data_service.file_service import FileService
from app.services.data_service.table_service import TableService
from app.services.supabase_service import SupabaseService


class DataService:
    """
    Unified, session-scoped data access layer.

    Parameters
    ──────────
    session_id : str             — the owning session (used as partition key)
    supabase   : SupabaseService — shared singleton from app.state
    bucket     : str             — Supabase Storage bucket (default: nirnaya-sessions)
    """

    def __init__(
        self,
        session_id: str,
        supabase: SupabaseService,
        *,
        bucket: str = "nirnaya-sessions",
    ) -> None:
        self._session_id = session_id
        self._supabase = supabase

        # Sub-services — created once per DataService instance
        self._table = TableService(session_id=session_id, supabase=supabase)
        self._file = FileService(session_id=session_id, supabase=supabase, bucket=bucket)

    @property
    def session_id(self) -> str:
        """The session_id this DataService is scoped to."""
        return self._session_id

    @property
    def table(self) -> TableService:
        """Access the PostgreSQL table operations for this session."""
        return self._table

    @property
    def file(self) -> FileService:
        """Access the Storage file operations for this session."""
        return self._file


__all__ = [
    "DataService",
    "TableService",
    "FileService",
]
