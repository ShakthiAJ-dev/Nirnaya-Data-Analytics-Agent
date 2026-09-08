"""
app/services/data_service/table_service.py
------------------------------------------
TableService — Supabase PostgreSQL (PostgREST) operations, session-partitioned.

Responsibilities
────────────────
1. Table auto-creation  — ensure tables exist before first use (DDL via RPC).
2. CRUD operations      — insert, upsert, select, delete rows.
3. Schema validation    — validate data against the registered Pydantic TableModel
                          before any DB write.
4. Session partitioning — every query is automatically scoped to session_id,
                          so each session's data is logically isolated.

Design
──────
• Wraps SupabaseService (the admin client is used for all ops here, since this
  is a server-side service and we need to bypass RLS for session-scoped data).
• Table existence is cached per-process in a set so we only run DDL once.
• All public methods are async-safe (supabase-py v2 uses httpx async).

Usage
─────
    from app.services.data_service import DataService

    ds = DataService(session_id="abc-123", supabase=supabase_service)
    await ds.table.ensure_table("chat_history")
    await ds.table.insert("chat_history", {"role": "user", "content": "Hello"})
    rows = await ds.table.select("chat_history")
"""

from __future__ import annotations

import textwrap
from typing import Any

from app.core.exceptions import DatabaseException
from app.core.logging import get_logger
from app.schemas.data_models import TABLE_REGISTRY, TableModel
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

# In-process cache of tables we've already ensured exist.
# Resets on server restart (acceptable — DDL is idempotent).
_ENSURED_TABLES: set[str] = set()


# ---------------------------------------------------------------------------
# DDL template (CREATE TABLE IF NOT EXISTS)
# ---------------------------------------------------------------------------
# We derive the column list from the Pydantic model's field annotations.
# Postgres type is mapped via _python_type_to_pg().
# session_id is always the first column after id (partition key + index).

_DDL_TEMPLATE = textwrap.dedent("""\
    CREATE TABLE IF NOT EXISTS {table_name} (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        session_id TEXT        NOT NULL,
    {columns}
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_{table_name}_session
        ON {table_name}(session_id);
""")


def _python_type_to_pg(annotation: Any) -> str:
    """Map a Python type annotation to a Postgres column type."""
    import typing
    origin = getattr(annotation, "__origin__", None)

    # Optional[X] → unwrap X
    if origin is typing.Union:
        args = [a for a in annotation.__args__ if a is not type(None)]
        if args:
            return _python_type_to_pg(args[0])

    if annotation in (str,):
        return "TEXT"
    if annotation in (int,):
        return "BIGINT"
    if annotation in (float,):
        return "DOUBLE PRECISION"
    if annotation in (bool,):
        return "BOOLEAN"
    if annotation in (dict, list) or origin in (dict, list):
        return "JSONB"

    # Fallback for complex / unknown types → TEXT
    return "TEXT"


def _build_ddl(model_cls: type[TableModel]) -> str:
    """Derive a CREATE TABLE DDL string from a TableModel subclass."""
    # Skip meta-fields that are handled explicitly in the template
    skip = {"session_id", "id", "created_at", "table_name"}

    col_lines: list[str] = ["    session_id TEXT NOT NULL,"]

    fields = model_cls.model_fields
    for name, field_info in fields.items():
        if name in skip:
            continue
        annotation = field_info.annotation
        pg_type = _python_type_to_pg(annotation)
        nullable = "    " if field_info.is_required() else "    "  # all nullable at DB level for flexibility
        col_lines.append(f"    {name} {pg_type},")

    # Remove trailing comma from last column line (before created_at)
    if col_lines:
        last = col_lines[-1]
        if last.endswith(","):
            col_lines[-1] = last  # keep it — created_at follows in template

    columns = "\n".join(col_lines)
    table_name = model_cls.table_name

    return f"""
CREATE TABLE IF NOT EXISTS {table_name} (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
{columns}
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_{table_name}_session
    ON {table_name}(session_id);
"""


# ---------------------------------------------------------------------------
# TableService
# ---------------------------------------------------------------------------

class TableService:
    """
    Session-scoped Supabase table operations.

    Every read/write is automatically filtered by session_id, providing
    logical partitioning per session inside a shared Postgres table.

    Parameters
    ──────────
    session_id  : str            — the owning session (partition key)
    supabase    : SupabaseService — shared singleton from app.state
    """

    def __init__(self, session_id: str, supabase: SupabaseService) -> None:
        self._session_id = session_id
        self._supa = supabase

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    async def ensure_table(self, table_name: str) -> None:
        """
        Ensure the given table exists in Postgres. Creates it if absent.

        Uses the Pydantic model registered in TABLE_REGISTRY to derive
        the column schema. The DDL is idempotent (IF NOT EXISTS).

        Caches the result in-process so DDL only runs once per server boot.

        Raises DatabaseException if the table is not in TABLE_REGISTRY.
        """
        if table_name in _ENSURED_TABLES:
            return

        model_cls = TABLE_REGISTRY.get(table_name)
        if model_cls is None:
            raise DatabaseException(
                f"Table '{table_name}' is not registered in TABLE_REGISTRY. "
                "Add a TableModel subclass to app/schemas/data_models.py first."
            )

        ddl = _build_ddl(model_cls)

        try:
            # Execute raw SQL via Supabase RPC helper.
            # The admin client bypasses RLS so DDL works regardless of policies.
            await self._supa.admin.rpc(
                "exec_ddl", {"sql": ddl}
            ).execute()
            _ENSURED_TABLES.add(table_name)
            logger.info("table_ensured", table=table_name)
        except Exception as exc:
            err = str(exc).lower()
            # If the function doesn't exist we'll fall back to a direct approach.
            # In most Supabase projects you need to create this SQL function:
            #   CREATE OR REPLACE FUNCTION exec_ddl(sql text)
            #   RETURNS void LANGUAGE plpgsql AS $$ BEGIN EXECUTE sql; END; $$;
            if "pgrst202" in err or "could not find" in err:
                logger.warning(
                    "exec_ddl_rpc_missing",
                    hint=(
                        "Create the exec_ddl(sql text) SQL function in Supabase. "
                        "See docstring in table_service.py."
                    ),
                )
                # Optimistically mark as ensured — table might already exist
                _ENSURED_TABLES.add(table_name)
            else:
                raise DatabaseException(f"Failed to ensure table '{table_name}': {exc}") from exc

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    def _validate(self, table_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Validate `data` against the registered Pydantic model for `table_name`.
        Always injects session_id and strips DB-generated fields (id, created_at).
        Returns a clean dict ready for INSERT/UPSERT.
        """
        model_cls = TABLE_REGISTRY.get(table_name)
        if model_cls is None:
            raise DatabaseException(
                f"No model registered for table '{table_name}'. "
                "Cannot validate data."
            )

        # Inject partition key
        data = {**data, "session_id": self._session_id}

        # Validate via Pydantic (raises ValidationError on bad data)
        record = model_cls.model_validate(data)

        # Build insert payload — exclude DB-generated fields
        payload = record.model_dump(exclude={"id", "created_at", "table_name"}, exclude_none=True)
        return payload

    # ------------------------------------------------------------------
    # CRUD — Insert
    # ------------------------------------------------------------------

    async def insert(
        self,
        table_name: str,
        data: dict[str, Any],
        *,
        auto_ensure: bool = True,
    ) -> dict[str, Any]:
        """
        Validate and insert a single row into `table_name`.

        Parameters
        ──────────
        table_name  : registered table name
        data        : row data (session_id is injected automatically)
        auto_ensure : call ensure_table() before insert (default True)

        Returns the inserted row (with id + created_at from Postgres).
        """
        if auto_ensure:
            await self.ensure_table(table_name)

        payload = self._validate(table_name, data)

        try:
            resp = await (
                self._supa.admin
                .table(table_name)
                .insert(payload)
                .execute()
            )
            rows = resp.data
            if not rows:
                raise DatabaseException(f"INSERT into '{table_name}' returned no data.")
            logger.info("table_row_inserted", table=table_name, session_id=self._session_id)
            return rows[0]
        except DatabaseException:
            raise
        except Exception as exc:
            raise DatabaseException(f"INSERT into '{table_name}' failed: {exc}") from exc

    # ------------------------------------------------------------------
    # CRUD — Upsert
    # ------------------------------------------------------------------

    async def upsert(
        self,
        table_name: str,
        data: dict[str, Any],
        *,
        on_conflict: str = "id",
        auto_ensure: bool = True,
    ) -> dict[str, Any]:
        """
        Upsert a row — insert or update on conflict.

        Parameters
        ──────────
        on_conflict : comma-separated column(s) for conflict resolution
        """
        if auto_ensure:
            await self.ensure_table(table_name)

        payload = self._validate(table_name, data)

        try:
            resp = await (
                self._supa.admin
                .table(table_name)
                .upsert(payload, on_conflict=on_conflict)
                .execute()
            )
            rows = resp.data
            if not rows:
                raise DatabaseException(f"UPSERT into '{table_name}' returned no data.")
            return rows[0]
        except DatabaseException:
            raise
        except Exception as exc:
            raise DatabaseException(f"UPSERT into '{table_name}' failed: {exc}") from exc

    # ------------------------------------------------------------------
    # CRUD — Select
    # ------------------------------------------------------------------

    async def select(
        self,
        table_name: str,
        *,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order_by: str | None = "created_at",
        ascending: bool = True,
        limit: int | None = None,
        auto_ensure: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Select rows for this session from `table_name`.

        session_id filter is always applied automatically.

        Parameters
        ──────────
        columns   : PostgREST column selector (default "*")
        filters   : additional {column: value} equality filters
        order_by  : column to order by (default "created_at")
        ascending : sort direction
        limit     : max rows to return
        """
        if auto_ensure:
            await self.ensure_table(table_name)

        try:
            query = (
                self._supa.admin
                .table(table_name)
                .select(columns)
                .eq("session_id", self._session_id)
            )

            if filters:
                for col, val in filters.items():
                    query = query.eq(col, val)

            if order_by:
                query = query.order(order_by, desc=not ascending)

            if limit is not None:
                query = query.limit(limit)

            resp = await query.execute()
            return resp.data or []
        except Exception as exc:
            raise DatabaseException(f"SELECT from '{table_name}' failed: {exc}") from exc

    # ------------------------------------------------------------------
    # CRUD — Delete
    # ------------------------------------------------------------------

    async def delete(
        self,
        table_name: str,
        *,
        row_id: int | None = None,
        filters: dict[str, Any] | None = None,
        auto_ensure: bool = True,
    ) -> int:
        """
        Delete rows for this session from `table_name`.

        Always scoped to session_id. Optionally narrow by row_id or filters.
        Returns the count of deleted rows.

        WARNING: Calling delete() without row_id or filters will delete ALL
        rows for this session in the table.
        """
        if auto_ensure:
            await self.ensure_table(table_name)

        try:
            query = (
                self._supa.admin
                .table(table_name)
                .delete()
                .eq("session_id", self._session_id)
            )

            if row_id is not None:
                query = query.eq("id", row_id)

            if filters:
                for col, val in filters.items():
                    query = query.eq(col, val)

            resp = await query.execute()
            count = len(resp.data) if resp.data else 0
            logger.info(
                "table_rows_deleted",
                table=table_name,
                session_id=self._session_id,
                count=count,
            )
            return count
        except Exception as exc:
            raise DatabaseException(f"DELETE from '{table_name}' failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Convenience — ChatHistory helpers
    # ------------------------------------------------------------------

    async def append_chat_message(
        self,
        role: str,
        content: str,
        *,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Shortcut to insert a chat history row for this session."""
        return await self.insert(
            "chat_history",
            {
                "role": role,
                "content": content,
                "project_id": project_id,
                "metadata": metadata,
            },
        )

    async def get_chat_history(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return all chat history for this session, oldest first."""
        return await self.select(
            "chat_history",
            order_by="created_at",
            ascending=True,
            limit=limit,
        )
