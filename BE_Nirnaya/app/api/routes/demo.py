"""
app/api/routes/demo.py
-----------------------
Demo project routes — no user credentials required.

Endpoints:
  GET  /api/v1/demo/project  — fetch demo project metadata from Supabase storage
  POST /api/v1/demo/chat     — chat against the demo dataset using server-side Bedrock
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.services.data_service import DataService
from app.services.llm_service import LLMService

router = APIRouter(prefix="/demo", tags=["Demo"])

# The demo files live under demo/ in the nirnaya-sessions bucket.
# FileService prepends session_id, so session_id="demo" resolves
# demo/metadata/demo_database.json correctly.
_DEMO_SESSION_ID = "demo"
_DEMO_METADATA_PATH = "metadata/demo_database.json"


async def _fetch_demo_metadata(request: Request) -> dict[str, Any]:
    """
    Download and parse the demo metadata JSON from Supabase Storage
    using the existing FileService (session_id='demo' → bucket path demo/metadata/...).
    """
    supabase = request.app.state.supabase_service
    ds = DataService(session_id=_DEMO_SESSION_ID, supabase=supabase)
    raw_bytes: bytes = await ds.file.download(_DEMO_METADATA_PATH)
    return json.loads(raw_bytes)


@router.get("/project")
async def get_demo_project_metadata(request: Request) -> dict[str, Any]:
    """
    Fetches the demo project metadata from Supabase Storage and structures
    it for the frontend.
    """
    try:
        raw_metadata = await _fetch_demo_metadata(request)

        # Build structured datasets list from the tables map
        datasets: list[dict[str, Any]] = []
        for table_name, table_data in raw_metadata.get("tables", {}).items():
            datasets.append({
                "name": f"{table_name}.sql",
                "tableName": table_name,
                "rows": table_data.get("row_count", 0),
                "columns": [col["name"] for col in table_data.get("columns", [])],
                "description": table_data.get("overview", ""),
                "useCase": table_data.get("use_case", ""),
                "keyNotes": table_data.get("key_notes", ""),
                "domainTags": table_data.get("domain_tags", []),
            })


        return {
            "id": "demo-project",
            "name": "Music E-commerce (Demo)",
            "description": "Pre-loaded Music E-commerce dataset — ask questions about sales, tracks, customers and more.",
            "is_demo": True,
            "datasets": datasets,
            "raw_metadata": raw_metadata,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load demo metadata: {exc}",
        )


class DemoChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def demo_chat(request: Request, body: DemoChatRequest) -> dict[str, Any]:
    """
    Handles chat for the demo project using the server's Bedrock config.
    Fetches demo schema context and sends it alongside the user message.
    """
    try:
        raw_metadata = await _fetch_demo_metadata(request)

        # Build schema context from tables
        schema_lines: list[str] = []
        for table_name, table_data in raw_metadata.get("tables", {}).items():
            cols = ", ".join(col["name"] for col in table_data.get("columns", []))
            row_count = table_data.get("row_count", 0)
            overview = table_data.get("overview", "")
            schema_lines.append(
                f"Table `{table_name}` ({row_count} rows)\n"
                f"  Columns: {cols}\n"
                f"  Description: {overview}"
            )

        schema_context = "\n\n".join(schema_lines)

        system_prompt = (
            "You are Nirnaya, an expert AI Data Analytics Assistant. "
            "You are operating in Demo Mode on a Music E-commerce PostgreSQL dataset. "
            "When asked about data or analysis, answer based on the schema below. "
            "If the user asks for SQL, generate accurate queries against these tables. "
            "Be concise, insightful, and professional.\n\n"
            "## Database Schema\n\n"
            f"{schema_context}"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=body.message),
        ]

        llm = LLMService(session_id="demo_session")
        response = await llm.ainvoke(
            messages=messages,
            model="claude-3-5-sonnet",
            provider="anthropic",
            request_type="demo_chat",
        )

        return {"reply": response.content}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Demo chat failed: {exc}")


@router.get("/tables/{table_name}/preview")
async def demo_preview_table(
    table_name: str,
    request: Request,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Preview rows from a demo table. No auth required."""
    try:
        raw_metadata = await _fetch_demo_metadata(request)
        schema_name = (
            raw_metadata.get("schema_name")
            or raw_metadata.get("schema")
            or "demo"
        )
        table_meta = raw_metadata.get("tables", {}).get(table_name)
        if table_meta is None:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found in demo.")
        supabase = request.app.state.supabase_service
        from app.services.database_service import DatabaseService
        ds = DatabaseService(session_id="demo", supabase=supabase)
        data = await ds._preview_by_schema(
            schema_name, table_name,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Demo preview failed: {exc}")
