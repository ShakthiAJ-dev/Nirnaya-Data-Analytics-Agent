"""
app/api/routes/projects.py
--------------------------
Project management routes. All require Bearer token auth.

POST   /api/v1/projects                     — create project
GET    /api/v1/projects                     — list projects for session
GET    /api/v1/projects/{project_id}        — get single project
PATCH  /api/v1/projects/{project_id}/title  — update title
DELETE /api/v1/projects/{project_id}        — delete project
"""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import SessionException
from app.core.logging import get_logger
from app.schemas.project import ProjectCreate, ProjectTitleUpdate
from app.services.project_service import ProjectService
from app.services.session_service import verify_token

logger = get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["Projects"])


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


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new project (chat)")
async def create_project(body: ProjectCreate, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    project = await ProjectService(session_id, _supabase(request)).create(
        database_id=body.database_id
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content={"success": True, "data": project})


@router.get("", status_code=status.HTTP_200_OK, summary="List projects for session")
async def list_projects(request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    projects = await ProjectService(session_id, _supabase(request)).list()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": {"projects": projects, "total": len(projects)}},
    )


@router.get("/{project_id}", status_code=status.HTTP_200_OK, summary="Get a single project")
async def get_project(project_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    project = await ProjectService(session_id, _supabase(request)).get(project_id)
    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": project})


@router.patch("/{project_id}/title", status_code=status.HTTP_200_OK, summary="Update project title")
async def update_project_title(
    project_id: str, body: ProjectTitleUpdate, request: Request, redis: RedisDep
) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    project = await ProjectService(session_id, _supabase(request)).update_title(project_id, body.title)
    return JSONResponse(status_code=status.HTTP_200_OK, content={"success": True, "data": project})


@router.delete("/{project_id}", status_code=status.HTTP_200_OK, summary="Delete a project")
async def delete_project(project_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    session_id, _ = await _require_session(request, redis)
    await ProjectService(session_id, _supabase(request)).delete(project_id)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": None, "message": "Project deleted."},
    )
