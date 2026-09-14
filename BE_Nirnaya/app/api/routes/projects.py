"""
app/api/routes/projects.py
--------------------------
Project management routes. All require Bearer token auth.

POST   /api/v1/projects                                    — create project
GET    /api/v1/projects                                    — list projects for session
GET    /api/v1/projects/{project_id}                       — get single project
GET    /api/v1/projects/{project_id}/messages              — get full chat history for a project
PATCH  /api/v1/projects/{project_id}/title                 — update title
DELETE /api/v1/projects/{project_id}                       — delete project (cascades messages + artifacts)
DELETE /api/v1/projects/{project_id}/messages/{message_id} — delete a single turn + its artifacts
"""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import SessionException
from app.core.logging import get_logger
from app.schemas.project import ProjectCreate, ProjectTitleUpdate
from app.services.chat_service import ChatService, CHAT_MESSAGES_TABLE, ARTIFACTS_TABLE
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


@router.get(
    "/{project_id}/messages",
    status_code=status.HTTP_200_OK,
    summary="Get full chat history for a project",
    description=(
        "Returns all completed turns for a project in chronological order. "
        "Call this on page load to hydrate the chat UI before opening the WebSocket. "
        "Each turn includes: turn_id, user_message, markdown, artifact_ids, artifacts, "
        "follow_up_questions, execution_time_ms, and created_at. "
        "Incomplete turns (still running) are excluded."
    ),
)
async def get_project_messages(project_id: str, request: Request, redis: RedisDep) -> JSONResponse:
    """
    FE page-load endpoint: hydrates the full conversation history for a project.

    Response shape:
    {
        "success": true,
        "data": {
            "project_id": "<uuid>",
            "turns": [
                {
                    "turn_id": "<uuid>",
                    "user_message": "What is revenue by country?",
                    "markdown": "Here is the revenue breakdown...",
                    "artifact_ids": ["<uuid>"],
                    "artifacts": [{"id": "<uuid>", ...}],
                    "follow_up_questions": ["...", "..."],
                    "execution_time_ms": 4821,
                    "seq": 1,
                    "created_at": "2026-09-12T15:30:00Z"
                }
            ],
            "total": 3
        }
    }
    """
    session_id, _ = await _require_session(request, redis)
    chat_svc = ChatService(session_id, _supabase(request))
    rows = await chat_svc.get_all_turns(project_id)

    # Collect all unique artifact IDs across all turns
    all_artifact_ids: list[str] = []
    seen = set()
    for row in rows:
        output = row.get("output") or {}
        for aid in output.get("artifact_ids", []):
            if aid not in seen:
                seen.add(aid)
                all_artifact_ids.append(aid)

    # ── Single batch fetch — one DB round-trip for ALL artifacts across all turns ─
    # Uses ChatService.get_artifacts_batch which already scopes by session_id.
    artifact_map: dict[str, dict] = {}
    if all_artifact_ids:
        artifact_rows = await chat_svc.get_artifacts_batch(all_artifact_ids)
        for art in artifact_rows:
            art_id = art.get("id", "")
            if art_id:
                # Normalise to match the WS `final` event artifact shape exactly
                # so FE uses one shared renderer for both live and historical turns.
                artifact_map[art_id] = {
                    "artifact_id":   art_id,                        # key matches WS final
                    "type":          art.get("type", ""),
                    "title":         art.get("title", ""),
                    "note":          art.get("note", ""),
                    "key_numbers":   art.get("key_numbers") or {},
                    "status":        art.get("status", "fresh"),
                    "error_message": art.get("error_message"),
                    "config":        art.get("config") or {},
                    "result_data":   art.get("result_data") or [],
                    "sql_query":     art.get("sql_query", ""),
                }

    # ── Build turn list with inlined artifact payloads and steps ─────────────
    turns: list[dict] = []
    for row in rows:
        output = row.get("output") or {}
        artifact_ids: list[str] = output.get("artifact_ids", [])
        # Preserve the ordering from artifact_ids; silently skip inaccessible IDs
        artifacts = [artifact_map[aid] for aid in artifact_ids if aid in artifact_map]
        turns.append({
            "turn_id":             row["id"],
            "user_message":        row["user_message"],
            "markdown":            output.get("markdown", ""),
            "artifact_ids":        artifact_ids,   # kept for reference / backwards-compat
            "artifacts":           artifacts,       # full payloads — same shape as WS final
            "steps":               output.get("steps", []),  # ordered step events for timeline
            "follow_up_questions": output.get("follow_up_questions", []),
            "execution_time_ms":   output.get("execution_time_ms"),
            "seq":                 row.get("seq"),
            "created_at":          row.get("created_at"),
        })

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "data": {
                "project_id": project_id,
                "turns": turns,
                "total": len(turns),
            },
        },
    )


@router.delete(
    "/{project_id}/messages/{message_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a single chat turn and its artifacts",
    description=(
        "Deletes a chat_messages row by its turn_id (message_id) and "
        "cascades to delete all associated artifact rows. "
        "Scoped to the authenticated session — cannot delete other sessions' data."
    ),
)
async def delete_message(
    project_id: str,
    message_id: str,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    """
    Cascading delete: removes the turn row AND all artifact rows whose
    message_id matches. The artifacts table has ON DELETE SET NULL on
    message_id, so we explicitly delete them first before deleting the turn.
    """
    session_id, _ = await _require_session(request, redis)
    supa = _supabase(request)

    # Verify the project belongs to this session (ownership check)
    await ProjectService(session_id, supa).get(project_id)

    # 1. Delete artifacts linked to this message
    try:
        await (
            supa.admin.table(ARTIFACTS_TABLE)
            .delete()
            .eq("message_id", message_id)
            .eq("session_id", session_id)
            .execute()
        )
    except Exception as exc:
        logger.warning("delete_message_artifacts_failed", message_id=message_id, error=str(exc))
        # Non-fatal — continue to delete the message row

    # 2. Delete the chat_messages row itself
    try:
        resp = await (
            supa.admin.table(CHAT_MESSAGES_TABLE)
            .delete()
            .eq("id", message_id)
            .eq("project_id", project_id)
            .eq("session_id", session_id)
            .execute()
        )
        if not resp.data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"success": False, "error": {"code": "NOT_FOUND", "message": "Message not found."}},
            )
    except Exception as exc:
        logger.error("delete_message_failed", message_id=message_id, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": {"code": "DELETE_FAILED", "message": str(exc)}},
        )

    logger.info("message_deleted", message_id=message_id, project_id=project_id, session_id=session_id)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "data": None, "message": "Message and associated artifacts deleted."},
    )
