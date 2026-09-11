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
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.exceptions import (
    DatabaseException,
    NotFoundException,
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
# Postgres type classification (for column stats strategy)
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = frozenset({
    "integer", "bigint", "smallint", "numeric", "decimal",
    "real", "double precision", "float4", "float8", "int2", "int4", "int8",
    "money",
})
_DATETIME_TYPES = frozenset({
    "timestamp", "timestamp without time zone", "timestamp with time zone",
    "timestamptz", "date", "time", "time without time zone", "time with time zone",
    "timetz", "interval",
})
_BOOLEAN_TYPES = frozenset({"boolean", "bool"})
_UUID_TYPES = frozenset({"uuid"})
_JSON_TYPES = frozenset({"json", "jsonb"})
_ARRAY_TYPES = frozenset({"array", "anyarray", "integer[]", "text[]", "bigint[]"})
_BINARY_TYPES = frozenset({"bytea"})
_ENUM_TYPES = frozenset({"user-defined"})


def _type_class(data_type: str) -> str:
    dt = data_type.lower().strip()
    if dt in _NUMERIC_TYPES:
        return "numeric"
    if dt in _DATETIME_TYPES:
        return "datetime"
    if dt in _BOOLEAN_TYPES:
        return "boolean"
    if dt in _UUID_TYPES:
        return "uuid"
    if dt in _JSON_TYPES:
        return "json"
    if dt in _ARRAY_TYPES or dt.endswith("[]"):
        return "array"
    if dt in _BINARY_TYPES:
        return "binary"
    if dt in _ENUM_TYPES:
        return "enum"
    return "text"


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

    async def _run_query(self, sql: str) -> list[dict[str, Any]]:
        """Run a SELECT query via exec_query RPC, return rows as list of dicts."""
        try:
            resp = await self._supa.admin.rpc("exec_query", {"sql": sql}).execute()
            data = resp.data
            if data is None:
                return []
            if isinstance(data, str):
                data = json.loads(data)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("exec_query_failed", sql=sql, error=str(exc))
            return []

    async def _query_table_stats(
        self, schema_name: str, table_name: str
    ) -> dict[str, Any]:
        """
        Query Postgres directly for column metadata, stats, and sample rows.

        Returns
        -------
        {
            "columns": [...],       # per-column stat objects
            "row_count": int,
            "column_count": int,
            "sample_rows": [...]    # 5 rows, _row_id excluded
        }
        """
        # Column info from information_schema
        col_info = await self._run_query(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table_name}' "
            f"ORDER BY ordinal_position"
        )

        # Row count
        rc = await self._run_query(
            f"SELECT COUNT(*) AS row_count FROM {schema_name}.{table_name}"
        )
        row_count = int(rc[0]["row_count"]) if rc else 0

        columns: list[dict[str, Any]] = []
        visible_col_names: list[str] = []

        for ci in col_info:
            col_name: str = ci["column_name"]
            if col_name == "_row_id":
                continue

            data_type: str = ci["data_type"]
            nullable: bool = ci.get("is_nullable", "YES").upper() == "YES"
            tc = _type_class(data_type)
            visible_col_names.append(col_name)

            col_meta: dict[str, Any] = {
                "name": col_name,
                "data_type": data_type,
                "type_class": tc,
                "nullable": nullable,
            }

            if tc == "numeric":
                rows = await self._run_query(
                    f'SELECT MIN("{col_name}") AS min_val, '
                    f'MAX("{col_name}") AS max_val, '
                    f'ROUND(AVG("{col_name}"::numeric), 4) AS avg_val, '
                    f'COUNT(*) FILTER (WHERE "{col_name}" IS NULL) AS null_count, '
                    f'COUNT(DISTINCT "{col_name}") AS unique_values_count '
                    f'FROM {schema_name}.{table_name}'
                )
                if rows:
                    s = rows[0]
                    col_meta["min"] = float(s["min_val"]) if s["min_val"] is not None else None
                    col_meta["max"] = float(s["max_val"]) if s["max_val"] is not None else None
                    col_meta["avg"] = float(s["avg_val"]) if s["avg_val"] is not None else None
                    col_meta["null_count"] = int(s["null_count"])
                    col_meta["unique_values_count"] = int(s["unique_values_count"])

            elif tc in ("datetime",):
                rows = await self._run_query(
                    f'SELECT MIN("{col_name}"::text) AS min_val, '
                    f'MAX("{col_name}"::text) AS max_val, '
                    f'COUNT(*) FILTER (WHERE "{col_name}" IS NULL) AS null_count, '
                    f'COUNT(DISTINCT "{col_name}") AS unique_values_count '
                    f'FROM {schema_name}.{table_name}'
                )
                if rows:
                    s = rows[0]
                    col_meta["min"] = s.get("min_val")
                    col_meta["max"] = s.get("max_val")
                    col_meta["null_count"] = int(s["null_count"])
                    col_meta["unique_values_count"] = int(s["unique_values_count"])

            else:
                # text, uuid, boolean, json, array, binary, enum, other
                rows = await self._run_query(
                    f'SELECT COUNT(DISTINCT "{col_name}") AS unique_values_count, '
                    f'COUNT(*) FILTER (WHERE "{col_name}" IS NULL) AS null_count '
                    f'FROM {schema_name}.{table_name}'
                )
                if rows:
                    s = rows[0]
                    unique_count = int(s["unique_values_count"])
                    col_meta["null_count"] = int(s["null_count"])
                    col_meta["unique_values_count"] = unique_count

                    if unique_count < 50:
                        val_rows = await self._run_query(
                            f'SELECT DISTINCT "{col_name}" AS val '
                            f'FROM {schema_name}.{table_name} '
                            f'WHERE "{col_name}" IS NOT NULL ORDER BY val LIMIT 50'
                        )
                        col_meta["unique_values"] = [r["val"] for r in val_rows]

            columns.append(col_meta)

        # Sample rows (5, _row_id excluded)
        if visible_col_names:
            cols_sql = ", ".join(f'"{c}"' for c in visible_col_names)
            sample_rows = await self._run_query(
                f"SELECT {cols_sql} FROM {schema_name}.{table_name} LIMIT 5"
            )
        else:
            sample_rows = []

        return {
            "columns": columns,
            "row_count": row_count,
            "column_count": len(columns),
            "sample_rows": sample_rows,
        }

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
        import asyncio

        try:
            resp = await (
                self._supa.admin.table(DATABASES_TABLE)
                .select("*")
                .eq("session_id", self._session_id)
                .order("created_at", desc=False)
                .execute()
            )
            databases = resp.data or []
        except Exception as exc:
            raise DatabaseException(f"List databases failed: {exc}") from exc

        async def _attach_metadata(db: dict[str, Any]) -> dict[str, Any]:
            path = db.get("metadata_path")
            if not path:
                db["metadata"] = None
                return db
            try:
                raw = await self._supa.admin.storage.from_(BUCKET).download(path)
                db["metadata"] = json.loads(raw) if raw else None
            except Exception:
                db["metadata"] = None
            return db

        return list(await asyncio.gather(*[_attach_metadata(db) for db in databases]))

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
        - DROP SCHEMA CASCADE.
        - Remove storage files and metadata.
        - Delete file_uploads and databases table entries.
        """
        db = await self.get_database(database_id)
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
    # Demo database
    # ------------------------------------------------------------------

    async def create_demo_database(self) -> dict[str, Any]:
        """
        Create a Music E-commerce database pre-loaded with demo parquet files.
        Idempotent: returns the existing record if the demo was already created.

        Steps:
        1. Create database + schema (skip if already exists)
        2. Ingest all parquet files from app/demo database files/
        3. Upload pre-built metadata JSON (no LLM call)
        """
        import pathlib

        DEMO_NAME = "Music E-commerce"
        DEMO_DIR = pathlib.Path(__file__).parent.parent / "demo database files"
        DEMO_META_FILE = DEMO_DIR / "demo_database.json"

        # Idempotent: return existing if already created
        schema_name = make_schema_name(self._session_id, DEMO_NAME)
        existing = await self._get_by_schema(schema_name)
        if existing:
            return existing

        db = await self.create_database(DEMO_NAME)
        database_id = db["id"]
        schema_name = db["schema_name"]

        pd = _import_pandas()
        now = datetime.now(timezone.utc).isoformat()

        for parquet_path in sorted(DEMO_DIR.glob("*.parquet")):
            table_name = parquet_path.stem
            df = pd.read_parquet(parquet_path)
            df.columns = [_sanitize(str(c), max_len=60) for c in df.columns]
            result = await self._ingest_dataframe(schema_name, table_name, df)
            try:
                await self._supa.admin.table(FILE_UPLOADS_TABLE).insert({
                    "session_id":        self._session_id,
                    "database_id":       database_id,
                    "filename":          parquet_path.name,
                    "original_filename": parquet_path.name,
                    "table_name":        table_name,
                    "row_count":         result["row_count"],
                    "status":            "ready",
                    "created_at":        now,
                }).execute()
            except Exception as exc:
                logger.warning("demo_file_upload_record_failed", table=table_name, error=str(exc))

        # Normalize demo_database.json to standard metadata format
        try:
            raw_meta = json.loads(DEMO_META_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("demo_metadata_read_failed", error=str(exc))
            raw_meta = {}

        # Use raw table data as-is — all stats are pre-computed and correct
        metadata: dict[str, Any] = {
            "database_name":  DEMO_NAME,
            "schema_name":    schema_name,
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "generated_by":   "nirnaya-demo",
            "business_rules": raw_meta.get("business_rules", []),
            "tables":         raw_meta.get("tables", {}),
        }

        meta_path = f"{self._session_id}/metadata/{database_id}.json"
        try:
            await self._supa.upload_file(
                BUCKET,
                meta_path,
                json.dumps(metadata, indent=2, default=str).encode("utf-8"),
                content_type="application/json",
                upsert=True,
            )
            await (
                self._supa.admin.table(DATABASES_TABLE)
                .update({"metadata_path": meta_path})
                .eq("id", database_id)
                .execute()
            )
            db["metadata_path"] = meta_path
        except Exception as exc:
            logger.warning("demo_metadata_upload_failed", error=str(exc))

        logger.info("demo_database_created", database_id=database_id, session_id=self._session_id)
        return db

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

        # Conflict check: reject if any table name already exists in this schema
        new_table_names = [name for name, _ in dataframes]
        existing_info = await self._run_query(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{schema_name}'"
        )
        existing_names = {row["table_name"] for row in existing_info}
        conflicts = [n for n in new_table_names if n in existing_names]
        if conflicts:
            raise ValidationException(
                f"Table(s) already exist in this database: {', '.join(conflicts)}. "
                "Delete them first or rename the file/sheet."
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
            database_id, db["name"], db["schema_name"], list(tables_for_metadata.keys())
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

    async def get_presigned_upload_url(self, database_id: str, filename: str) -> dict[str, Any]:
        """Generate a presigned URL for direct FE upload to Supabase Storage."""
        # Verify db ownership
        await self.get_database(database_id)
        
        file_path = f"{self._session_id}/databases/{database_id}/{uuid.uuid4().hex}_{filename}"
        
        try:
            # Note: create_signed_upload_url returns a dict like {'signedUrl': '...'}
            resp = await self._supa.admin.storage.from_(BUCKET).create_signed_upload_url(file_path)
            # The python SDK may return a dict or an object depending on version. We'll handle both.
            url = ""
            if isinstance(resp, dict):
                url = resp.get("signedUrl") or resp.get("signedURL", "")
            elif hasattr(resp, "signedUrl"):
                url = resp.signedUrl
            else:
                url = str(resp)

            return {
                "upload_url": url,
                "file_path": file_path,
                "expires_in": 3600
            }
        except Exception as exc:
            raise DatabaseException(f"Failed to generate presigned upload URL: {exc}") from exc

    async def process_presigned_upload(self, database_id: str, file_path: str, filename: str) -> list[dict[str, Any]]:
        """Download file from presigned path, process it, then delete from storage."""
        try:
            file_bytes = await self._supa.admin.storage.from_(BUCKET).download(file_path)
            if not file_bytes:
                raise ValidationException("File not found or empty in storage.")
                
            results = await self.upload_file(database_id, file_bytes, filename)
            
            await self._supa.admin.storage.from_(BUCKET).remove([file_path])
            
            return results
        except ValidationException:
            raise
        except Exception as exc:
            raise DatabaseException(f"Failed to process upload: {exc}") from exc

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
        schema_name: str,
        table_names: list[str],
    ) -> str | None:
        """
        1. Load existing metadata from storage (to preserve business_rules).
        2. Query Postgres for factual stats per table.
        3. Call LLM for semantic enrichment (per-table overviews, tags, etc.).
        4. Merge and upload final metadata JSON.
        """
        path = f"{self._session_id}/metadata/{database_id}.json"

        # Load existing metadata to preserve tables already there + business_rules
        existing_tables: dict[str, dict] = {}
        existing_business_rules: list[dict] = []
        try:
            raw = await self._supa.admin.storage.from_(BUCKET).download(path)
            if raw:
                existing = json.loads(raw)
                existing_tables = existing.get("tables", {})
                existing_business_rules = existing.get("business_rules", [])
        except Exception:
            pass  # no prior metadata — start fresh

        # Query factual stats only for the new tables being added
        query_stats: dict[str, dict] = {}
        for table_name in table_names:
            try:
                query_stats[table_name] = await self._query_table_stats(schema_name, table_name)
            except Exception as exc:
                logger.warning("query_stats_failed", table=table_name, error=str(exc))
                query_stats[table_name] = {
                    "columns": [], "row_count": 0, "column_count": 0, "sample_rows": []
                }

        # LLM semantic enrichment for new tables only
        llm_result = await self._call_llm_for_metadata(db_name, query_stats)

        # Build entries for new tables
        new_tables: dict[str, dict] = {}
        for table_name, qs in query_stats.items():
            llm_table = (llm_result or {}).get("tables", {}).get(table_name, {})
            new_tables[table_name] = {
                "overview":      llm_table.get("overview", f"Table '{table_name}'."),
                "use_case":      llm_table.get("use_case", ""),
                "grain":         llm_table.get("grain", "One row per record."),
                "domain_tags":   llm_table.get("domain_tags", []),
                "key_columns":   llm_table.get("key_columns", []),
                "currency":      llm_table.get("currency"),
                "timezone":      llm_table.get("timezone"),
                "tenant_column": llm_table.get("tenant_column"),
                "key_notes":     llm_table.get("key_notes", ""),
                "pii_columns":   llm_table.get("pii_columns", []),
                "row_count":     qs["row_count"],
                "column_count":  qs["column_count"],
                "columns":       qs["columns"],
                "sample_rows":   qs["sample_rows"],
            }

        # Merge: existing tables first, then new/updated entries
        merged_tables = {**existing_tables, **new_tables}

        metadata: dict[str, Any] = {
            "database_name":  db_name,
            "schema_name":    schema_name,
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "generated_by":   "nirnaya-llm" if llm_result else "nirnaya-stats-fallback",
            "business_rules": existing_business_rules,
            "tables":         merged_tables,
        }

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
                "use_case": f"Query and analyse data from '{table_name}'.",
                "grain": "One row per record.",
                "domain_tags": [],
                "key_columns": [s["name"] for s in stats[:5]],
                "currency": None,
                "timezone": None,
                "tenant_column": None,
                "key_notes": "",
                "pii_columns": [],
                "row_count": td["row_count"],
                "column_count": len(stats),
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
            }
        return {
            "database_name": db_name,
            "database_overview": f"User-uploaded database '{db_name}'.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "nirnaya-stats-fallback",
            "business_rules": [],
            "tables": tables,
        }

    async def _call_llm_for_metadata(
        self,
        db_name: str,
        query_stats: dict[str, dict],
    ) -> dict[str, Any] | None:
        """
        Call Bedrock Haiku for semantic metadata only.
        LLM receives column stats + sample rows; returns overview/use_case/grain/
        domain_tags/key_columns/currency/timezone/tenant_column/key_notes/pii_columns.
        No column details, no business_rules — those are handled separately.
        Returns None on any failure (caller uses fallback).
        """
        try:
            from langchain_aws import ChatBedrockConverse
            from langchain_core.messages import HumanMessage, SystemMessage

            table_summaries: list[str] = []
            for table_name, qs in query_stats.items():
                col_lines = []
                for c in qs["columns"]:
                    line = f"  - {c['name']} ({c['data_type']}, class={c['type_class']}, nullable={c['nullable']}, unique_values_count={c.get('unique_values_count', '?')}, null_count={c.get('null_count', '?')})"
                    if "min" in c:
                        line += f", min={c['min']}, max={c['max']}, avg={c['avg']}"
                    if "unique_values" in c:
                        vals = c["unique_values"][:10]
                        line += f", sample_values={vals}"
                    col_lines.append(line)

                table_summaries.append(
                    f"TABLE: {table_name} ({qs['row_count']} rows, {qs['column_count']} columns)\n"
                    + "\n".join(col_lines)
                    + f"\nSample rows (first 3): {json.dumps(qs['sample_rows'][:3], default=str)}"
                )

            system_prompt = textwrap.dedent("""
                You are a database documentation assistant. Analyse the column statistics and sample rows provided.
                Return ONLY a JSON object (no markdown, no explanation) with this exact structure:

                {
                  "tables": {
                    "<table_name>": {
                      "overview": "<2-3 sentences describing what this table contains and its purpose>",
                      "use_case": "<what business questions can be answered from this table>",
                      "grain": "<one row represents one ...>",
                      "domain_tags": ["<relevant business domain tags, e.g. finance, sales, hr>"],
                      "key_columns": ["<most important columns for analysis>"],
                      "currency": "<currency code if monetary columns exist, else null>",
                      "timezone": "<timezone if datetime columns exist, else null>",
                      "tenant_column": "<column that partitions by tenant/customer if any, else null>",
                      "key_notes": "<important caveats analysts must know: null handling, units, edge cases. Empty string if none.>",
                      "pii_columns": ["<column names containing PII such as names, emails, addresses. Empty list if none.>"]
                    }
                  }
                }

                Rules:
                - Infer currency, timezone, pii_columns from column names and sample values.
                - Return ONLY valid JSON.
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
                    + "\n\n".join(table_summaries)
                    + "\n\nGenerate the metadata JSON."
                )),
            ])

            content = result.content
            if isinstance(content, list):
                content = "".join(
                    c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                )
            content = content.strip()
            if content.startswith("```"):
                parts = content.split("```")
                content = parts[1] if len(parts) > 1 else content
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)

        except Exception as exc:
            logger.warning("llm_metadata_generation_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    async def get_metadata(self, database_id: str) -> dict[str, Any] | None:
        """Download and return the metadata JSON for a database. None if not found."""
        db = await self.get_database(database_id)
        path = db.get("metadata_path")
        if not path:
            return None
        try:
            raw = await self._supa.admin.storage.from_(BUCKET).download(path)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("get_metadata_failed", database_id=database_id, error=str(exc))
            return None

    async def update_business_rules(
        self,
        database_id: str,
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Replace business_rules in the stored metadata with the provided list.
        FE sends the complete list each time.
        Returns the updated metadata dict.
        """
        db = await self.get_database(database_id)
        path = db.get("metadata_path")
        if not path:
            raise NotFoundException(f"No metadata found for database {database_id!r}.")

        metadata = await self.get_metadata(database_id)
        if metadata is None:
            raise NotFoundException("Metadata file not found in storage.")

        metadata["business_rules"] = rules
        try:
            await self._supa.upload_file(
                BUCKET,
                path,
                json.dumps(metadata, indent=2, default=str).encode("utf-8"),
                content_type="application/json",
                upsert=True,
            )
        except Exception as exc:
            raise DatabaseException(f"Failed to update business rules: {exc}") from exc

        logger.info("business_rules_updated", database_id=database_id, count=len(rules))
        return metadata

    # ------------------------------------------------------------------
    # Delete table
    # ------------------------------------------------------------------

    async def delete_table(self, database_id: str, table_name: str) -> None:
        """
        Drop a table from the database schema and remove it from metadata.
        Also deletes the file_uploads record for that table.
        """
        db = await self.get_database(database_id)
        schema_name = db["schema_name"]

        # Drop from Postgres
        await self._exec_sql(
            f'DROP TABLE IF EXISTS {schema_name}."{table_name}" CASCADE;'
        )

        # Remove from metadata JSON
        metadata_path = db.get("metadata_path")
        if metadata_path:
            try:
                raw = await self._supa.admin.storage.from_(BUCKET).download(metadata_path)
                if raw:
                    metadata = json.loads(raw)
                    metadata.get("tables", {}).pop(table_name, None)
                    await self._supa.upload_file(
                        BUCKET,
                        metadata_path,
                        json.dumps(metadata, indent=2, default=str).encode("utf-8"),
                        content_type="application/json",
                        upsert=True,
                    )
            except Exception as exc:
                logger.warning("delete_table_metadata_update_failed", error=str(exc))

        # Delete file_uploads record
        try:
            await (
                self._supa.admin.table(FILE_UPLOADS_TABLE)
                .delete()
                .eq("database_id", database_id)
                .eq("table_name", table_name)
                .execute()
            )
        except Exception as exc:
            logger.warning("delete_table_file_upload_record_failed", error=str(exc))

        logger.info("table_deleted", database_id=database_id, table=table_name)

    # ------------------------------------------------------------------
    # Preview table rows
    # ------------------------------------------------------------------

    async def preview_table(
        self, database_id: str, table_name: str, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Return paginated rows from a table. Excludes _row_id column."""
        db = await self.get_database(database_id)
        schema_name = db["schema_name"]
        return await self._preview_by_schema(schema_name, table_name, limit, offset)

    async def _preview_by_schema(
        self, schema_name: str, table_name: str, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Core preview logic by schema_name (used by both user and demo preview)."""
        col_info = await self._run_query(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table_name}' "
            f"AND column_name != '_row_id' ORDER BY ordinal_position"
        )
        col_names = [c["column_name"] for c in col_info]
        if not col_names:
            return {
                "rows": [], "columns": [], "total_count": 0,
                "has_more": False, "offset": offset, "limit": limit,
            }
        cols_sql = ", ".join(f'"{c}"' for c in col_names)
        # Use _row_id for stable ordering only if it exists on this table
        has_row_id_result = await self._run_query(
            f"SELECT 1 FROM information_schema.columns "
            f"WHERE table_schema = '{schema_name}' AND table_name = '{table_name}' "
            f"AND column_name = '_row_id' LIMIT 1"
        )
        order_clause = "ORDER BY _row_id" if has_row_id_result else ""
        rows = await self._run_query(
            f"SELECT {cols_sql} FROM {schema_name}.\"{table_name}\" "
            f"{order_clause} LIMIT {limit} OFFSET {offset}"
        )
        rc = await self._run_query(
            f"SELECT COUNT(*) AS cnt FROM {schema_name}.\"{table_name}\""
        )
        total = int(rc[0]["cnt"]) if rc else 0
        # Serialize rows (convert non-JSON-safe types)
        safe_rows = []
        for row in rows:
            safe_row = {}
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    safe_row[k] = v.isoformat()
                else:
                    safe_row[k] = v
            safe_rows.append(safe_row)
        return {
            "rows": safe_rows,
            "columns": col_names,
            "total_count": total,
            "has_more": (offset + limit) < total,
            "offset": offset,
            "limit": limit,
        }

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    async def _delete_storage_folder(self, folder_path: str) -> int:
        """
        Recursively delete all files under folder_path in the session bucket.
        Returns total files deleted. Folders appear as items without an 'id'.
        """
        deleted = 0
        try:
            items = await self._supa.admin.storage.from_(BUCKET).list(folder_path)
            if not items:
                return 0
            file_paths = [f"{folder_path}/{item['name']}" for item in items if item.get("id")]
            subfolder_names = [item["name"] for item in items if not item.get("id")]
            if file_paths:
                await self._supa.admin.storage.from_(BUCKET).remove(file_paths)
                deleted += len(file_paths)
            for sub in subfolder_names:
                deleted += await self._delete_storage_folder(f"{folder_path}/{sub}")
        except Exception as exc:
            logger.debug("storage_folder_delete_failed", path=folder_path, error=str(exc))
        return deleted

    async def cleanup_session(self) -> dict[str, Any]:
        """
        Delete ALL data for this session:
          - Checkpoint rows (checkpoints, checkpoint_blobs, checkpoint_writes)
          - All user database schemas + uploaded files + metadata
          - Projects (CASCADE → chat_messages, artifacts)
          - Entire storage root folder {session_id}/
        """
        errors: list[dict] = []

        # 1. Collect turn_ids BEFORE deleting (needed to clean checkpoint tables)
        turn_ids: list[str] = []
        try:
            resp = await (
                self._supa.admin.table("chat_messages")
                .select("id")
                .eq("session_id", self._session_id)
                .execute()
            )
            turn_ids = [r["id"] for r in (resp.data or [])]
        except Exception as exc:
            logger.warning("cleanup_collect_turns_failed", error=str(exc))

        # 2. Delete LangGraph checkpoint rows for all turns in this session
        if turn_ids:
            id_list = ", ".join(f"'{tid}'" for tid in turn_ids)
            for cp_table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                try:
                    await self._exec_sql(
                        f"DELETE FROM public.{cp_table} WHERE thread_id IN ({id_list});"
                    )
                except Exception as exc:
                    # Tables won't exist when MemorySaver is used — safe to skip
                    logger.debug(
                        "cleanup_checkpoint_skip",
                        table=cp_table,
                        error=str(exc)[:120],
                    )

        # 3. Delete all user databases (DROP SCHEMA + storage files + DB records)
        databases = await self.list_databases()
        deleted_databases: list[str] = []
        for db in databases:
            try:
                await self.delete_database(db["id"])
                deleted_databases.append(db["id"])
            except Exception as exc:
                errors.append({"database_id": db["id"], "error": str(exc)})
                logger.warning("cleanup_db_failed", database_id=db["id"], error=str(exc))

        # 4. Delete projects → CASCADE deletes chat_messages + artifacts
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

        # 5. Sweep any remaining storage files under {session_id}/
        storage_deleted = await self._delete_storage_folder(self._session_id)

        logger.info(
            "session_cleanup_done",
            session_id=self._session_id,
            databases_deleted=len(deleted_databases),
            projects_deleted=deleted_projects,
            checkpoint_turns_cleaned=len(turn_ids),
            storage_files_deleted=storage_deleted,
        )
        return {
            "databases_deleted": len(deleted_databases),
            "projects_deleted": deleted_projects,
            "turns_cleaned": len(turn_ids),
            "storage_files_deleted": storage_deleted,
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

        # exec_query: used for SELECT queries in _run_query
        exec_query_fn = textwrap.dedent("""
            CREATE OR REPLACE FUNCTION exec_query(sql text)
            RETURNS json LANGUAGE plpgsql SECURITY DEFINER AS $$
            DECLARE result json;
            BEGIN
              EXECUTE format('SELECT json_agg(t) FROM (%s) t', sql) INTO result;
              RETURN COALESCE(result, '[]'::json);
            END;
            $$;
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
                        "RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN EXECUTE sql; END; $$;"
                    ),
                )
                return
            else:
                logger.error("app_tables_init_failed", error=str(exc))

        try:
            await supabase.admin.rpc("exec_ddl", {"sql": exec_query_fn}).execute()
            logger.info("exec_query_function_ready")
        except Exception as exc:
            logger.warning("exec_query_fn_setup_failed", error=str(exc))
