"""
app/services/database_service.py
----------------------------------
Database management service.

Each user database = a Postgres schema: n_{12-char-session-hex}_{sanitized-name}
File uploads are parsed (CSV/Parquet/Excel) and stored as tables in that schema.
Metadata is generated via LLM and stored at {session_id}/metadata/{database_id}.json
in the nirnaya-sessions Supabase Storage bucket.

Schema operations and data insertion use the exec_ddl RPC (runs arbitrary SQL
as service role). INSERT statements are batched in chunks of INSERT_BATCH_SIZE.

Table models: DatabaseRecord, FileUploadRecord in app/schemas/data_models.py.
"""
from __future__ import annotations

import io
import json
import re
import textwrap
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.exceptions import (
    DatabaseException,
    NotFoundException,
    PermissionException,
    ValidationException,
)
from app.core.logging import get_logger
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

DATABASES_TABLE = "databases"
FILE_UPLOADS_TABLE = "file_uploads"
BUCKET = "nirnaya-sessions"
INSERT_BATCH_SIZE = 200


# ---------------------------------------------------------------------------
# Identifier helpers
# ---------------------------------------------------------------------------

def _sanitize(name: str, max_len: int = 40) -> str:
    """Convert arbitrary string to valid Postgres identifier fragment."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower()).strip("_")
    if not clean or clean[0].isdigit():
        clean = "t_" + clean
    return clean[:max_len]


def make_schema_name(session_id: str, db_name: str) -> str:
    """
    Stable Postgres schema name for a user database.
    Format: n_{12 hex chars from session_id}_{sanitized db_name}  (≤63 chars)
    """
    sid = re.sub(r"[^a-fA-F0-9]", "", session_id)[:12].lower()
    db = _sanitize(db_name, max_len=46)
    return f"n_{sid}_{db}"


# ---------------------------------------------------------------------------
# SQL value escaping
# ---------------------------------------------------------------------------

def _sql_val(val: Any) -> str:
    """Escape a Python value for safe inclusion in a SQL literal."""
    if val is None or (isinstance(val, float) and val != val):  # None / NaN
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if hasattr(val, "isoformat"):
        return "'" + val.isoformat().replace("'", "''") + "'"
    return "'" + str(val).replace("'", "''") + "'"


def _pd_type_to_pg(dtype_str: str) -> str:
    """Map pandas dtype string to Postgres column type."""
    d = dtype_str.lower()
    if "int" in d:
        return "BIGINT"
    if "float" in d:
        return "DOUBLE PRECISION"
    if "bool" in d:
        return "BOOLEAN"
    if "datetime" in d or "timestamp" in d:
        return "TIMESTAMPTZ"
    return "TEXT"


# ---------------------------------------------------------------------------
# Lazy pandas import
# ---------------------------------------------------------------------------

def _import_pandas():
    try:
        import pandas as pd
        return pd
    except ImportError as exc:
        raise ValidationException(
            "pandas is required for file uploads. "
            "Install: pip install pandas openpyxl pyarrow"
        ) from exc


# ---------------------------------------------------------------------------
# DatabaseService
# ---------------------------------------------------------------------------

class DatabaseService:
    """
    Manages user databases scoped to a session.

    Parameters
    ----------
    session_id : str            — owning session
    supabase   : SupabaseService — shared singleton from app.state
    """

    def __init__(self, session_id: str, supabase: SupabaseService) -> None:
        self._session_id = session_id
        self._supa = supabase

    # ------------------------------------------------------------------
    # Internal: SQL execution via exec_ddl RPC
    # ------------------------------------------------------------------

    async def _exec_sql(self, sql: str) -> None:
        """Run arbitrary SQL (DDL or DML) via exec_ddl RPC (service role)."""
        try:
            await self._supa.admin.rpc("exec_ddl", {"sql": sql}).execute()
        except Exception as exc:
            err = str(exc).lower()
            if "pgrst202" in err or "could not find" in err:
                logger.warning(
                    "exec_ddl_rpc_missing",
                    hint="Create exec_ddl(sql text) function in Supabase SQL editor.",
                )
                return
            raise DatabaseException(f"SQL execution failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_database(self, name: str) -> dict[str, Any]:
        """
        1. Generate schema name.
        2. Check uniqueness for this session.
        3. CREATE SCHEMA in Postgres.
        4. Insert record into public.databases.
        """
        schema_name = make_schema_name(self._session_id, name)

        existing = await self._get_by_schema(schema_name)
        if existing:
            raise ValidationException(f"Database {name!r} already exists in this session.")

        await self._exec_sql(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")

        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "session_id": self._session_id,
            "name": name,
            "schema_name": schema_name,
            "is_demo": False,
            "created_at": now,
        }
        try:
            resp = await self._supa.admin.table(DATABASES_TABLE).insert(payload).execute()
            if not resp.data:
                raise DatabaseException("Create database returned no data.")
            logger.info("database_created", name=name, schema=schema_name, session_id=self._session_id)
            return resp.data[0]
        except DatabaseException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Create database failed: {exc}") from exc

    async def _get_by_schema(self, schema_name: str) -> dict[str, Any] | None:
        try:
            resp = await (
                self._supa.admin.table(DATABASES_TABLE)
                .select("*")
                .eq("schema_name", schema_name)
                .execute()
            )
            rows = resp.data or []
            return rows[0] if rows else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_databases(self) -> list[dict[str, Any]]:
        try:
            resp = await (
                self._supa.admin.table(DATABASES_TABLE)
                .select("*")
                .eq("session_id", self._session_id)
                .order("created_at", desc=False)
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            raise DatabaseException(f"List databases failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    async def get_database(self, database_id: str) -> dict[str, Any]:
        try:
            resp = await (
                self._supa.admin.table(DATABASES_TABLE)
                .select("*")
                .eq("id", database_id)
                .eq("session_id", self._session_id)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                raise NotFoundException(f"Database {database_id!r} not found.")
            return rows[0]
        except NotFoundException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Get database failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_database(self, database_id: str) -> None:
        """
        - Reject demo databases.
        - DROP SCHEMA CASCADE.
        - Remove storage files and metadata.
        - Delete file_uploads and databases table entries.
        """
        db = await self.get_database(database_id)

        if db.get("is_demo"):
            raise PermissionException("Cannot delete the demo database.")

        schema_name = db["schema_name"]

        await self._exec_sql(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")

        # Delete raw file storage
        try:
            prefix = f"{self._session_id}/databases/{database_id}"
            files = await self._supa.admin.storage.from_(BUCKET).list(prefix)
            if files:
                paths = [f"{prefix}/{f['name']}" for f in files]
                await self._supa.admin.storage.from_(BUCKET).remove(paths)
        except Exception as exc:
            logger.warning("delete_db_storage_failed", error=str(exc))

        # Delete metadata file
        try:
            meta_path = db.get("metadata_path")
            if meta_path:
                await self._supa.admin.storage.from_(BUCKET).remove([meta_path])
        except Exception as exc:
            logger.warning("delete_db_metadata_failed", error=str(exc))

        # Remove file_uploads records
        try:
            await (
                self._supa.admin.table(FILE_UPLOADS_TABLE)
                .delete()
                .eq("database_id", database_id)
                .execute()
            )
        except Exception as exc:
            logger.warning("delete_file_uploads_failed", error=str(exc))

        # Remove database record
        try:
            await (
                self._supa.admin.table(DATABASES_TABLE)
                .delete()
                .eq("id", database_id)
                .eq("session_id", self._session_id)
                .execute()
            )
        except Exception as exc:
            raise DatabaseException(f"Delete database record failed: {exc}") from exc

        logger.info("database_deleted", database_id=database_id, session_id=self._session_id)

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        database_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> list[dict[str, Any]]:
        """
        Parse file → create tables in schema → insert rows → generate metadata.

        Supported formats: .csv, .parquet, .xlsx, .xls
        Excel: one table per sheet (table name = sanitized sheet name).
        Returns list of {table_name, row_count, columns} dicts.
        """
        pd = _import_pandas()
        db = await self.get_database(database_id)
        schema_name = db["schema_name"]

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        base_name = _sanitize(filename.rsplit(".", 1)[0] if "." in filename else filename, max_len=50)

        dataframes: list[tuple[str, Any]] = []

        if ext == "csv":
            df = pd.read_csv(io.BytesIO(file_bytes))
            dataframes.append((base_name, df))
        elif ext == "parquet":
            df = pd.read_parquet(io.BytesIO(file_bytes))
            dataframes.append((base_name, df))
        elif ext in ("xlsx", "xls"):
            xf = pd.ExcelFile(io.BytesIO(file_bytes))
            for sheet in xf.sheet_names:
                sheet_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet)
                dataframes.append((_sanitize(str(sheet), max_len=50), sheet_df))
        else:
            raise ValidationException(
                f"Unsupported file type '.{ext}'. Supported: csv, parquet, xlsx, xls"
            )

        results = []
        tables_for_metadata: dict[str, dict] = {}

        for table_name, df in dataframes:
            df.columns = [_sanitize(str(c), max_len=60) for c in df.columns]
            result = await self._ingest_dataframe(schema_name, table_name, df)
            results.append(result)
            tables_for_metadata[table_name] = {"df": df, "result": result}

            now = datetime.now(timezone.utc).isoformat()
            try:
                await self._supa.admin.table(FILE_UPLOADS_TABLE).insert({
                    "session_id": self._session_id,
                    "database_id": database_id,
                    "filename": f"{table_name}.{ext}",
                    "original_filename": filename,
                    "table_name": table_name,
                    "row_count": result["row_count"],
                    "status": "ready",
                    "created_at": now,
                }).execute()
            except Exception as exc:
                logger.warning("file_upload_record_failed", error=str(exc))

        # Generate and store metadata
        metadata_path = await self._generate_and_store_metadata(
            database_id, db["name"], tables_for_metadata
        )
        if metadata_path:
            try:
                await (
                    self._supa.admin.table(DATABASES_TABLE)
                    .update({"metadata_path": metadata_path})
                    .eq("id", database_id)
                    .execute()
                )
            except Exception as exc:
                logger.warning("update_metadata_path_failed", error=str(exc))

        return results

    async def _ingest_dataframe(
        self, schema_name: str, table_name: str, df: Any
    ) -> dict[str, Any]:
        """CREATE TABLE in schema, then batch-INSERT all rows via exec_ddl."""
        cols = list(df.columns)
        col_defs = ",\n    ".join(
            f"{c} {_pd_type_to_pg(str(df[c].dtype))}" for c in cols
        )
        await self._exec_sql(textwrap.dedent(f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{table_name} (
                _row_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                {col_defs}
            );
        """))

        rows = df.where(df.notna(), other=None).to_dict(orient="records")
        col_list = ", ".join(cols)

        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            batch = rows[i : i + INSERT_BATCH_SIZE]
            values_parts = [
                "(" + ", ".join(_sql_val(row.get(c)) for c in cols) + ")"
                for row in batch
            ]
            await self._exec_sql(
                f"INSERT INTO {schema_name}.{table_name} ({col_list}) VALUES "
                + ",\n".join(values_parts) + ";"
            )

        logger.info("table_ingested", schema=schema_name, table=table_name, rows=len(rows))
        return {"table_name": table_name, "row_count": len(rows), "columns": cols}

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    async def _generate_and_store_metadata(
        self,
        database_id: str,
        db_name: str,
        tables_data: dict[str, dict],
    ) -> str | None:
        tables_meta: dict[str, dict] = {}
        for table_name, td in tables_data.items():
            df = td["df"]
            stats = self._compute_stats(df)
            sample_rows = df.head(5).where(df.head(5).notna(), other=None).to_dict(orient="records")
            tables_meta[table_name] = {
                "column_stats": stats,
                "sample_rows": sample_rows,
                "row_count": td["result"]["row_count"],
            }

        metadata = await self._call_llm_for_metadata(db_name, tables_meta)
        if metadata is None:
            metadata = self._build_basic_metadata(db_name, tables_meta)

        path = f"{self._session_id}/metadata/{database_id}.json"
        try:
            await self._supa.upload_file(
                BUCKET,
                path,
                json.dumps(metadata, indent=2, default=str).encode("utf-8"),
                content_type="application/json",
                upsert=True,
            )
            logger.info("metadata_stored", path=path)
            return path
        except Exception as exc:
            logger.warning("metadata_store_failed", error=str(exc))
            return None

    def _compute_stats(self, df: Any) -> list[dict[str, Any]]:
        stats = []
        for col in df.columns:
            series = df[col]
            col_stat: dict[str, Any] = {
                "name": col,
                "dtype": str(series.dtype),
                "pg_type": _pd_type_to_pg(str(series.dtype)),
                "null_count": int(series.isna().sum()),
                "unique_count": int(series.nunique()),
                "sample_values": series.dropna().head(5).tolist(),
            }
            if str(series.dtype) in ("int64", "float64", "Int64", "Float64"):
                try:
                    col_stat["min"] = float(series.min()) if not series.empty else None
                    col_stat["max"] = float(series.max()) if not series.empty else None
                    col_stat["mean"] = float(series.mean()) if not series.empty else None
                except Exception:
                    pass
            stats.append(col_stat)
        return stats

    def _build_basic_metadata(
        self, db_name: str, tables_meta: dict[str, dict]
    ) -> dict[str, Any]:
        tables = {}
        for table_name, td in tables_meta.items():
            stats = td["column_stats"]
            tables[table_name] = {
                "overview": f"Table '{table_name}' with {td['row_count']} rows.",
                "grain": "One row per record.",
                "row_count": td["row_count"],
                "columns": [
                    {
                        "name": s["name"],
                        "type": s["pg_type"],
                        "description": s["name"].replace("_", " ").title(),
                        "nullable": s["null_count"] > 0,
                        "unique_count": s["unique_count"],
                        "null_count": s["null_count"],
                        "sample_values": s.get("sample_values", []),
                        **({"min": s["min"], "max": s["max"], "mean": s["mean"]}
                           if "min" in s else {}),
                    }
                    for s in stats
                ],
                "sample_rows": td["sample_rows"],
                "domain_tags": [],
                "pii_columns": [],
                "business_rules": [],
            }
        return {
            "database_name": db_name,
            "database_overview": f"User-uploaded database '{db_name}'.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "nirnaya-stats-fallback",
            "tables": tables,
        }

    async def _call_llm_for_metadata(
        self,
        db_name: str,
        tables_meta: dict[str, dict],
    ) -> dict[str, Any] | None:
        """Call Bedrock Haiku to generate rich metadata. Falls back to None on any failure."""
        try:
            from langchain_aws import ChatBedrockConverse
            from langchain_core.messages import HumanMessage, SystemMessage

            table_summaries = []
            for table_name, td in tables_meta.items():
                cols_desc = "\n".join(
                    f"  - {s['name']} ({s['pg_type']}, {s['unique_count']} unique, {s['null_count']} nulls)"
                    + (f", range [{s.get('min'):.2f}, {s.get('max'):.2f}]" if "min" in s else "")
                    for s in td["column_stats"]
                )
                sample = json.dumps(td["sample_rows"][:3], default=str)
                table_summaries.append(
                    f"Table: {table_name}\nColumns:\n{cols_desc}\nSample rows: {sample}"
                )

            system_prompt = textwrap.dedent("""
                You are a database documentation assistant. Given column statistics and sample data,
                generate structured metadata as a valid JSON object with this exact structure:
                {
                  "database_name": "<name>",
                  "database_overview": "<2-3 sentence description>",
                  "generated_at": "<ISO timestamp>",
                  "generated_by": "nirnaya-llm",
                  "tables": {
                    "<table_name>": {
                      "overview": "<1-2 sentence description>",
                      "grain": "<one row represents one ...>",
                      "row_count": <number>,
                      "columns": [
                        {
                          "name": "<col>",
                          "type": "<PG type>",
                          "description": "<brief description>",
                          "nullable": <bool>,
                          "unique_count": <number>,
                          "null_count": <number>,
                          "sample_values": [<up to 5 values>]
                        }
                      ],
                      "sample_rows": [<up to 5 rows>],
                      "domain_tags": ["<tag>"],
                      "pii_columns": ["<col if PII>"],
                      "business_rules": ["<rule if obvious>"]
                    }
                  }
                }
                Return ONLY valid JSON. No markdown. No explanation.
            """).strip()

            llm = ChatBedrockConverse(
                model=settings.bedrock_anthropic_model,
                region_name=getattr(settings, "bedrock_region", "us-east-1"),
                max_tokens=4096,
            )
            result = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=(
                    f"Database name: {db_name}\n\n"
                    f"Table statistics:\n\n" + "\n\n".join(table_summaries) +
                    "\n\nGenerate the metadata JSON."
                )),
            ])

            content = result.content
            if isinstance(content, list):
                content = "".join(
                    c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                )
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            metadata = json.loads(content)
            # Ensure actual row counts and sample rows from ingested data
            for table_name, td in tables_meta.items():
                if table_name in metadata.get("tables", {}):
                    metadata["tables"][table_name]["row_count"] = td["row_count"]
                    metadata["tables"][table_name]["sample_rows"] = td["sample_rows"]
            return metadata

        except Exception as exc:
            logger.warning("llm_metadata_generation_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    async def cleanup_session(self) -> dict[str, Any]:
        """Delete all databases and projects owned by this session."""
        databases = await self.list_databases()
        deleted_databases: list[str] = []
        errors: list[dict] = []

        for db in databases:
            try:
                await self.delete_database(db["id"])
                deleted_databases.append(db["id"])
            except Exception as exc:
                errors.append({"database_id": db["id"], "error": str(exc)})
                logger.warning("cleanup_db_failed", database_id=db["id"], error=str(exc))

        deleted_projects = 0
        try:
            resp = await (
                self._supa.admin.table("projects")
                .delete()
                .eq("session_id", self._session_id)
                .execute()
            )
            deleted_projects = len(resp.data) if resp.data else 0
        except Exception as exc:
            errors.append({"resource": "projects", "error": str(exc)})

        logger.info(
            "session_cleanup_done",
            session_id=self._session_id,
            databases_deleted=len(deleted_databases),
            projects_deleted=deleted_projects,
        )
        return {
            "databases_deleted": len(deleted_databases),
            "projects_deleted": deleted_projects,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # App table initialization (startup)
    # ------------------------------------------------------------------

    @staticmethod
    async def initialize_app_tables(supabase: SupabaseService) -> None:
        """
        Create public.projects, public.databases, public.file_uploads if absent.
        Called once at startup — idempotent.

        Requires the exec_ddl(sql text) SQL function to exist in Supabase:
            CREATE OR REPLACE FUNCTION exec_ddl(sql text)
            RETURNS void LANGUAGE plpgsql AS $$ BEGIN EXECUTE sql; END; $$;
        """
        ddl = textwrap.dedent("""
            CREATE TABLE IF NOT EXISTS public.projects (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id  TEXT NOT NULL,
                title       TEXT NOT NULL DEFAULT 'Untitled',
                database_id UUID,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_projects_session
                ON public.projects(session_id);

            CREATE TABLE IF NOT EXISTS public.databases (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id    TEXT NOT NULL,
                name          TEXT NOT NULL,
                schema_name   TEXT NOT NULL,
                is_demo       BOOLEAN NOT NULL DEFAULT FALSE,
                metadata_path TEXT,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_databases_schema
                ON public.databases(schema_name);
            CREATE INDEX IF NOT EXISTS idx_databases_session
                ON public.databases(session_id);

            CREATE TABLE IF NOT EXISTS public.file_uploads (
                id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id        TEXT NOT NULL,
                database_id       UUID NOT NULL,
                filename          TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                table_name        TEXT NOT NULL,
                row_count         BIGINT DEFAULT 0,
                status            TEXT NOT NULL DEFAULT 'pending',
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_file_uploads_database
                ON public.file_uploads(database_id);
            CREATE INDEX IF NOT EXISTS idx_file_uploads_session
                ON public.file_uploads(session_id);
        """).strip()

        try:
            await supabase.admin.rpc("exec_ddl", {"sql": ddl}).execute()
            logger.info("app_tables_initialized")
        except Exception as exc:
            err = str(exc).lower()
            if "pgrst202" in err or "could not find" in err:
                logger.warning(
                    "exec_ddl_missing",
                    hint=(
                        "Run in Supabase SQL editor: "
                        "CREATE OR REPLACE FUNCTION exec_ddl(sql text) "
                        "RETURNS void LANGUAGE plpgsql AS $$ BEGIN EXECUTE sql; END; $$;"
                    ),
                )
            else:
                logger.error("app_tables_init_failed", error=str(exc))
