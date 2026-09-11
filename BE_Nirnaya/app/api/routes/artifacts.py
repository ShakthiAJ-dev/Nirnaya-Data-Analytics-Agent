"""
app/api/routes/artifacts.py
----------------------------
Artifact retrieval endpoints.

POST /api/v1/artifacts/batch  � fetch multiple artifacts by ID in one query

All endpoints require Bearer token auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.dependencies import RedisDep, get_session_service
from app.core.exceptions import SessionException
from app.core.logging import get_logger
from app.services.chat_service import ChatService
from app.services.session_service import verify_token

logger = get_logger(__name__)
router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


async def _require_session(request: Request, redis: RedisDep):
    """Validate Bearer token -> session_id."""
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


class ArtifactBatchRequest(BaseModel):
    artifact_ids: list[str] = Field(
        ...,
        description="List of artifact UUIDs to retrieve.",
        min_length=1,
        max_length=50,
    )


@router.post(
    "/batch",
    status_code=status.HTTP_200_OK,
    summary="Fetch multiple artifacts by ID",
    description=(
        "Retrieve full details (config, result_data, sql_query, etc.) for a list "
        "of artifact IDs in a single request. Only artifacts owned by the "
        "authenticated session are returned. Missing IDs are silently omitted."
    ),
)
async def get_artifacts_batch(
    body: ArtifactBatchRequest,
    request: Request,
    redis: RedisDep,
) -> JSONResponse:
    session_id = await _require_session(request, redis)
    chat_svc = ChatService(session_id, _supabase(request))
    artifacts = await chat_svc.get_artifacts_batch(body.artifact_ids)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "data": {
                "artifacts": artifacts,
                "total": len(artifacts),
                "requested": len(body.artifact_ids),
            },
        },
    )

