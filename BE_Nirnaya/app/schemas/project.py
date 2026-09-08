from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    database_id: Optional[str] = Field(default=None, description="Optional database to link.")


class ProjectTitleUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    id: str
    session_id: str
    title: str
    database_id: Optional[str] = None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int
