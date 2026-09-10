"""
app/api/routes/demo.py
-----------------------
Demo project creation — creates a fully populated Music E-commerce database
and linked project for the calling session on demand.

POST /api/v1/demo/create — auth required, idempotent
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import SessionException
from app.core.logging import get_logger
from app.services.database_service import DatabaseService
from app.services.project_service import ProjectService
from app.services.session_service import verify_token

logger = get_logger(__name__)
router = APIRouter(prefix="/demo", tags=["Demo"])


async def _require_session(request: Request, redis: RedisDep):
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
    return session_id


def _supabase(request: Request):
    return request.app.state.supabase_service


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create demo project",
    description=(
        "Creates a Music E-commerce database with pre-loaded data and a linked project "
        "for the calling session. Idempotent — returns existing demo if already created."
    ),
)
async def create_demo_project(request: Request, redis: RedisDep) -> JSONResponse:
    session_id = await _require_session(request, redis)
    supabase = _supabase(request)

    db_service = DatabaseService(session_id, supabase)
    db = await db_service.create_demo_database()

    project_service = ProjectService(session_id, supabase)
    project = await project_service.create(database_id=db["id"])

    logger.info("demo_project_created", session_id=session_id, database_id=db["id"], project_id=project["id"])

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "project_id": project["id"],
            "database_id": db["id"],
            "title": project.get("title", "Untitled"),
            "database_name": db["name"],
            "schema_name": db["schema_name"],
            "metadata_path": db.get("metadata_path"),
        },
    )
