from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


class DatabaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      description="Human-readable database name.")


class DatabaseResponse(BaseModel):
    id: str
    session_id: str
    name: str
    schema_name: str
    metadata_path: Optional[str] = None
    table_count: int = 0
    created_at: str


class DatabaseListResponse(BaseModel):
    databases: List[DatabaseResponse]
    total: int


class TableUploadResult(BaseModel):
    table_name: str
    row_count: int
    columns: List[str]


class FileUploadResponse(BaseModel):
    database_id: str
    tables_created: List[TableUploadResult]
    metadata_path: Optional[str] = None
    message: str
