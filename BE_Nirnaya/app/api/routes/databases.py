"""
app/api/routes/databases.py
----------------------------
Database management + file upload routes. All require Bearer token auth.

POST   /api/v1/databases                       — create database
GET    /api/v1/databases                       — list databases for session
GET    /api/v1/databases/{database_id}         — get database details
DELETE /api/v1/databases/{database_id}         — delete database (not demo)
POST   /api/v1/databases/{database_id}/upload  — upload file into database
DELETE /api/v1/session/cleanup                 — cleanup all session data
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import SessionException, ValidationException
from app.core.logging import get_logger
from app.schemas.database import DatabaseCreate
from app.services.database_service import DatabaseService
from app.services.session_service import verify_token

logger = get_logger(__name__)
router = APIRouter(tags=["Databases"])

ALLOWED_EXTENSIONS = {"csv", "parquet", "xlsx", "xls"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


async def _require_session(request: Request, redis: RedisDep):
    """Validate Bearer token → (session_id, SessionService)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise SessionException("Missing or malformed Authorization header.")
    token = auth.removeprefix("Bearer ").strip()
    session_id = verify_token(token)
    if session_id is None:
        raise SessionException("Invalid or expired session token.")
    svc = get_session_service(redis)
    if not await svc.get_session(session_id):
        raise SessionException("Session not found or expired.")
    await svc.refresh_session(session_id)
    return session_id, svc


def _supabase(request: Request):
    return request.app.state.supabase_service


@router.post(
    "/databases",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new database",
    description="Creates a Postgres schema for the session. Upload files into it afterwards.",
)
async def create_database(body: DatabaseCreate, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    db = await DatabaseService(session_id, _supabase(request)).create_database(body.name)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content={"success": True, "data": db})


@router.get(
    "/databases",
    status_code=status.HTTP_200_OK,
    summary="List databases for session",
)
async def list_databases(request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    databases = await DatabaseService(session_id, _supabase(request)).list_databases()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": {"databases": databases, "total": len(databases)}},
    )


@router.get(
    "/databases/{database_id}",
    status_code=status.HTTP_200_OK,
    summary="Get database details",
)
async def get_database(database_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    db = await DatabaseService(session_id, _supabase(request)).get_database(database_id.strip())
    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": db})


@router.delete(
    "/databases/{database_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a database",
    description="Drops schema, removes files and metadata. Demo database cannot be deleted.",
)
async def delete_database(database_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    await DatabaseService(session_id, _supabase(request)).delete_database(database_id.strip())
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": None, "message": "Database deleted."},
    )


@router.post(
    "/databases/{database_id}/upload/presign",
    status_code=status.HTTP_200_OK,
    summary="Generate presigned upload URL",
    description="Returns a short-lived URL for the FE to directly upload to Supabase Storage.",
)
async def upload_presign(
    database_id: str,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    from pydantic import BaseModel
    class PresignBody(BaseModel):
        filename: str

    body = PresignBody.model_validate(await request.json())
    session_id, _ = await _require_session(request, redis)

    svc = DatabaseService(session_id, _supabase(request))
    data = await svc.get_presigned_upload_url(database_id.strip(), body.filename)

    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": data})


@router.post(
    "/databases/{database_id}/upload/process",
    status_code=status.HTTP_201_CREATED,
    summary="Process an uploaded file from a presigned path",
    description=(
        "Downloads the file from storage, parses it into Postgres tables, "
        "generates LLM metadata, and deletes the original file."
    ),
)
async def upload_process(
    database_id: str,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    from pydantic import BaseModel
    class ProcessBody(BaseModel):
        file_path: str
        filename: str

    body = ProcessBody.model_validate(await request.json())
    session_id, _ = await _require_session(request, redis)

    filename = body.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationException(
            f"File type '.{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    svc = DatabaseService(session_id, _supabase(request))
    database_id = database_id.strip()
    
    results = await svc.process_presigned_upload(database_id, body.file_path, filename)
    db = await svc.get_database(database_id)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "success": True,
            "data": {
                "database_id": database_id,
                "tables_created": results,
                "metadata_path": db.get("metadata_path"),
                "message": f"Uploaded {len(results)} table(s) successfully.",
            },
        },
    )


@router.get(
    "/databases/{database_id}/metadata",
    status_code=status.HTTP_200_OK,
    summary="Get database metadata",
    description="Returns the stored metadata JSON for a database.",
)
async def get_metadata(database_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    metadata = await DatabaseService(session_id, _supabase(request)).get_metadata(database_id.strip())
    if metadata is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": {"code": "NOT_FOUND", "message": "Metadata not yet generated for this database."}},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": metadata})


@router.put(
    "/databases/{database_id}/business-rules",
    status_code=status.HTTP_200_OK,
    summary="Update business rules",
    description="Replace the business rules list for this database. Send the complete list each time.",
)
async def update_business_rules(
    database_id: str,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    from pydantic import BaseModel
    class BusinessRulesBody(BaseModel):
        rules: list[dict]

    body = BusinessRulesBody.model_validate(await request.json())
    session_id, _ = await _require_session(request, redis)
    metadata = await DatabaseService(session_id, _supabase(request)).update_business_rules(
        database_id.strip(), body.rules
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": {"business_rules": metadata.get("business_rules", [])}, "message": "Business rules updated."},
    )


@router.delete(
    "/databases/{database_id}/tables/{table_name}",
    status_code=status.HTTP_200_OK,
    summary="Delete a table from a database",
    description="Drops the Postgres table, removes it from metadata, and deletes the upload record.",
)
async def delete_table(
    database_id: str, table_name: str, request: Request, redis: RedisDep
) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    await DatabaseService(session_id, _supabase(request)).delete_table(
        database_id.strip(), table_name.strip()
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": None, "message": f"Table '{table_name}' deleted."},
    )


@router.get(
    "/databases/{database_id}/tables/{table_name}/preview",
    status_code=status.HTTP_200_OK,
    summary="Preview table rows with pagination",
    description="Returns up to `limit` rows starting at `offset`. Max limit=100.",
)
async def preview_table(
    database_id: str,
    table_name: str,
    request: Request,
    redis: RedisDep,
    limit: int = 20,
    offset: int = 0,
) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    data = await DatabaseService(session_id, _supabase(request)).preview_table(
        database_id.strip(), table_name.strip(), limit=min(max(limit, 1), 100), offset=max(offset, 0)
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": data})


@router.delete(
    "/session/cleanup",
    status_code=status.HTTP_200_OK,
    summary="Cleanup all session data",
    description=(
        "Triggered by QStash after session TTL. Deletes all session data. "
        "Verifies Upstash-Signature when QStash signing keys are configured."
    ),
)
async def cleanup_session(request: Request, redis: RedisDep) -> JSONResponse:
    raw_body = await request.body()

    # Verify QStash signature when signing keys are present
    if settings.qstash_current_signing_key:
        from qstash import Receiver
        sig = request.headers.get("Upstash-Signature", "")
        if not sig:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Missing Upstash-Signature header."},
            )
        receiver = Receiver(
            current_signing_key=settings.qstash_current_signing_key,
            next_signing_key=settings.qstash_next_signing_key,
        )
        try:
            receiver.verify(signature=sig, body=raw_body.decode())
        except Exception as exc:
            logger.warning("qstash_signature_invalid", error=str(exc))
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Invalid QStash signature."},
            )

    body = json.loads(raw_body)
    session_id: str = body.get("session_id", "").strip()
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "session_id required in body."},
        )

    # DB + schemas + checkpoints + storage cleanup
    result = await DatabaseService(session_id, _supabase(request)).cleanup_session()

    # Redis cleanup: session metadata, API keys, chat history, rate-limit counters
    redis_deleted = 0
    try:
        for pattern in (
            f"nirnaya:session:{session_id}*",   # session + key + history
            f"nirnaya:rate:{session_id}*",       # rate-limit buckets
            f"nirnaya:cache:{session_id}*",      # any cache keyed by session
        ):
            async for key in redis.client.scan_iter(pattern):
                await redis.client.delete(key)
                redis_deleted += 1
    except Exception:
        pass

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "data": {**result, "redis_keys_deleted": redis_deleted},
            "message": "Session data cleaned up.",
        },
    )
