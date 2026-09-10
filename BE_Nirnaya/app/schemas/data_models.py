"""
app/schemas/data_models.py
--------------------------
Pydantic table-models for Supabase PostgreSQL tables managed by DataService.

Rules
─────
• Every table that DataService touches must have a TableModel here.
• The model defines column names, types, and validation constraints.
• The model is used for INSERT/UPSERT validation before any DB call.
• Table creation DDL is derived from the model at runtime by TableService.

Adding a new table
──────────────────
1. Subclass ``TableModel`` and set ``table_name``.
2. Declare fields matching your Postgres columns (Python type ↔ Postgres type
   mapping is handled in TableService._python_type_to_pg).
3. Export from ``__all__``.

Postgres type mapping (TableService uses this):
    str   → TEXT
    int   → BIGINT
    float → DOUBLE PRECISION
    bool  → BOOLEAN
    dict  → JSONB
    list  → JSONB
    Any datetime-like string → TEXT (store as ISO string)
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Base class — all table models inherit from this
# ---------------------------------------------------------------------------

class TableModel(BaseModel):
    """
    Base class for Supabase table schemas.

    ``table_name`` (class var) must be set by every subclass.
    ``session_id`` is always the partition key — every table has it.
    """

    # Subclasses MUST override this
    table_name: ClassVar[str] = ""

    # The partition key — present in every table
    session_id: str = Field(
        description="Session identifier — used as the partition key."
    )

    class Config:
        # Allow extra fields coming back from DB (e.g. created_at added by Postgres)
        extra = "allow"


# ---------------------------------------------------------------------------
# ChatHistory — dummy table for pipeline validation
# ---------------------------------------------------------------------------

class ChatHistoryRecord(TableModel):
    """
    Schema for the ``chat_history`` table in Supabase Postgres.

    Postgres table definition (auto-created by TableService if absent):
        CREATE TABLE IF NOT EXISTS chat_history (
            id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id    TEXT        NOT NULL,
            role          TEXT        NOT NULL,   -- 'user' | 'assistant' | 'system'
            content       TEXT        NOT NULL,
            metadata      JSONB,
            created_at    TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_chat_history_session
            ON chat_history(session_id);
    """

    table_name: ClassVar[str] = "chat_history"

    # ── Required fields ────────────────────────────────────────────────
    role: str = Field(
        description="Message role: 'user', 'assistant', or 'system'.",
        pattern=r"^(user|assistant|system)$",
    )
    content: str = Field(
        min_length=1,
        description="The text content of the message.",
    )

    # ── Optional fields ────────────────────────────────────────────────
    project_id: Optional[str] = Field(
        default=None,
        description="Project this message belongs to.",
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Arbitrary metadata (model used, token count, etc.).",
    )

    # ── DB-generated (not sent on INSERT) ─────────────────────────────
    id: Optional[int] = Field(
        default=None,
        description="Auto-generated primary key (set by Postgres).",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp set by Postgres DEFAULT NOW().",
    )


# ---------------------------------------------------------------------------
# ProjectRecord — public.projects
# ---------------------------------------------------------------------------

class ProjectRecord(TableModel):
    """
    Schema for the ``projects`` table.
    Each project is a chat/analysis session scoped to a session_id.
    Title starts as 'Untitled'; updated when the user asks their first question.

    Note: uses UUID PK (created_at startup via initialize_app_tables).
    TableService is not used for this model; ProjectService queries directly.
    """

    table_name: ClassVar[str] = "projects"

    title: str = Field(default="Untitled", description="Project title.")
    database_id: Optional[str] = Field(
        default=None, description="Linked database UUID, if any."
    )
    updated_at: Optional[str] = Field(
        default=None, description="ISO timestamp of last update."
    )
    id: Optional[str] = Field(default=None, description="UUID PK (set by Postgres).")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp.")


# ---------------------------------------------------------------------------
# DatabaseRecord — public.databases
# ---------------------------------------------------------------------------

class DatabaseRecord(TableModel):
    """
    Schema for the ``databases`` table.
    Each record represents a Postgres schema created for a session.

    Note: uses UUID PK; managed by DatabaseService directly.
    """

    table_name: ClassVar[str] = "databases"

    name: str = Field(description="Human-readable database name.")
    schema_name: str = Field(description="Actual Postgres schema name.")
    metadata_path: Optional[str] = Field(
        default=None,
        description="Storage path: {session_id}/metadata/{database_id}.json",
    )
    id: Optional[str] = Field(default=None, description="UUID PK (set by Postgres).")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp.")


# ---------------------------------------------------------------------------
# FileUploadRecord — public.file_uploads
# ---------------------------------------------------------------------------

class FileUploadRecord(TableModel):
    """
    Schema for the ``file_uploads`` table.
    Tracks each file/sheet ingested into a database schema.
    """

    table_name: ClassVar[str] = "file_uploads"

    database_id: str = Field(description="Parent database UUID.")
    filename: str = Field(description="Sanitized table-safe filename.")
    original_filename: str = Field(description="Original uploaded filename.")
    table_name_col: str = Field(
        alias="table_name",
        description="Table name within the database schema.",
        default="",
    )
    row_count: int = Field(default=0, description="Number of rows ingested.")
    status: str = Field(default="pending", description="pending | ready | error")
    id: Optional[str] = Field(default=None, description="UUID PK (set by Postgres).")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp.")

    class Config:
        extra = "allow"
        populate_by_name = True


# ---------------------------------------------------------------------------
# Registry — maps table_name → model class (used by TableService)
# ---------------------------------------------------------------------------

TABLE_REGISTRY: dict[str, type[TableModel]] = {
    ChatHistoryRecord.table_name: ChatHistoryRecord,
    ProjectRecord.table_name: ProjectRecord,
    DatabaseRecord.table_name: DatabaseRecord,
    FileUploadRecord.table_name: FileUploadRecord,
}

__all__ = [
    "TableModel",
    "ChatHistoryRecord",
    "ProjectRecord",
    "DatabaseRecord",
    "FileUploadRecord",
    "TABLE_REGISTRY",
]
