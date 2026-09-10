"""
app/websocket/sql_chat_agent/sql_executor.py
---------------------------------------------
Thin async SQL execution layer used by both the orchestrator (discovery queries)
and workers (analytical queries).

Security model
──────────────
- All generated SQL MUST reference the session-authorised schema (schema_name).
  Any SQL touching a different `n_` schema is rejected before execution.
- Query is wrapped in a LIMIT guard (5001 rows fetched; ≥5001 → truncated=True).
- Execution via exec_query RPC (SECURITY DEFINER — service role on server side).
- No SET search_path — all tables must be fully qualified as schema.table.

Redis caching (workers only)
─────────────────────────────
Workers call run_sql_cached(); orchestrator discovery uses run_sql_ephemeral()
which returns results inline WITHOUT caching. This keeps Redis clean —
only confirmed "will be turned into an artifact" results are cached.

Cache key: query:{turn_id}:{worker_id}:{query_id}   TTL: 45 min
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.core.logging import get_logger
from app.services.redis_service import RedisService
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

# Hard limits
_FETCH_ROW_CAP = 5001       # fetch +1 so we can detect truncation
_STORE_ROW_CAP = 1000       # rows persisted in artifacts.result_data
_PREVIEW_ROWS  = 20         # rows returned to the LLM in the tool response
_QUERY_CACHE_TTL = 2700     # 45 minutes


# ---------------------------------------------------------------------------
# Security: schema ownership check
# ---------------------------------------------------------------------------

def _validate_sql_schema(sql: str, authorized_schema: str) -> tuple[bool, str]:
    """
    Ensure the SQL only references the authorised schema.
    Blocks any other n_XXXXXX_ schema pattern.

    Returns (is_valid, error_message)
    """
    # Find all potential schema references — pattern: identifier.identifier
    # We look for `n_` prefixed schemas specifically (user data schemas)
    user_schema_refs = re.findall(r'\b(n_[a-z0-9_]+)\s*\.', sql, re.IGNORECASE)
    for ref in user_schema_refs:
        if ref.lower() != authorized_schema.lower():
            return False, f"SQL references unauthorized schema '{ref}'. Only '{authorized_schema}' is allowed."
    return True, ""


def _wrap_with_limit(sql: str, limit: int) -> str:
    """
    Wrap user SQL in a subquery with LIMIT if it doesn't already have one
    at the outer level that's <= our cap.
    """
    # Simple heuristic: check if SQL ends with a LIMIT clause
    stripped = sql.strip().rstrip(";")
    upper = stripped.upper()
    # If already has a top-level LIMIT, wrap anyway to enforce our cap
    return f"SELECT * FROM ({stripped}) AS __nirnaya_result LIMIT {limit}"


# ---------------------------------------------------------------------------
# Core execution function (shared)
# ---------------------------------------------------------------------------

async def _execute_query(
    sql: str,
    authorized_schema: str,
    supabase: SupabaseService,
    label: str = "",
) -> dict[str, Any]:
    """
    Execute a SELECT query via the exec_query RPC.

    Returns:
    {
      "columns": [...],
      "rows": [...],         # up to _FETCH_ROW_CAP rows
      "row_count": int,      # actual rows returned (before store cap)
      "truncated": bool,     # True if result was capped
      "error": str | None
    }
    """
    # 1. Schema ownership check
    valid, err_msg = _validate_sql_schema(sql, authorized_schema)
    if not valid:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "error": err_msg}

    # 2. Wrap with limit
    wrapped_sql = _wrap_with_limit(sql, _FETCH_ROW_CAP)

    try:
        resp = await supabase.admin.rpc("exec_query", {"sql": wrapped_sql}).execute()
        data = resp.data
        if data is None:
            return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "error": None}
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            data = []

        truncated = len(data) >= _FETCH_ROW_CAP
        rows = data[:(_FETCH_ROW_CAP - 1)]  # drop the +1 sentinel row

        columns = list(rows[0].keys()) if rows else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "error": None,
        }

    except Exception as exc:
        logger.warning("sql_executor_error", label=label, error=str(exc))
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Orchestrator: ephemeral discovery queries (NOT cached in Redis)
# ---------------------------------------------------------------------------

async def run_sql_ephemeral(
    queries: list[dict[str, str]],    # [{sql, label}]
    authorized_schema: str,
    supabase: SupabaseService,
    max_concurrent: int = 5,
) -> list[dict[str, Any]]:
    """
    Run one or more discovery queries for the orchestrator.
    Results are returned inline — NOT stored in Redis.

    Returns: [{label, query_id, columns, preview_rows, row_count, truncated, error}]
    """
    import asyncio

    async def _run_one(q: dict[str, str]) -> dict[str, Any]:
        result = await _execute_query(q["sql"], authorized_schema, supabase, label=q.get("label", ""))
        return {
            "label": q.get("label", ""),
            "query_id": str(uuid.uuid4()),   # ephemeral id, not cached
            "columns": result["columns"],
            "preview_rows": result["rows"][:_PREVIEW_ROWS],
            "row_count": result["row_count"],
            "truncated": result["truncated"],
            "error": result["error"],
        }

    # Respect max_concurrent limit
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _guarded(q: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            return await _run_one(q)

    return list(await asyncio.gather(*[_guarded(q) for q in queries]))


# ---------------------------------------------------------------------------
# Worker: SQL run + Redis cache (for artifact promotion later)
# ---------------------------------------------------------------------------

async def run_sql_cached(
    sql: str,
    label: str,
    authorized_schema: str,
    turn_id: str,
    worker_id: str,
    supabase: SupabaseService,
    redis: RedisService,
) -> dict[str, Any]:
    """
    Run a SQL query for a worker, cache full result (up to _STORE_ROW_CAP rows)
    in Redis, and return metadata + preview to the LLM.

    Redis key: nirnaya:cache:query:{turn_id}:{worker_id}:{query_id}
    TTL: 45 minutes (long enough to survive the turn; expires naturally after)

    Returns:
    {
      "query_id": str,
      "columns": [...],
      "preview_rows": [...],   # 20 rows — what the LLM sees
      "row_count": int,        # full count (before preview cap)
      "truncated": bool,
      "error": str | None
    }
    """
    result = await _execute_query(sql, authorized_schema, supabase, label=label)
    query_id = str(uuid.uuid4())

    if result["error"] is None:
        # Cap result data at _STORE_ROW_CAP before caching
        store_rows = result["rows"][:_STORE_ROW_CAP]
        cache_payload = {
            "sql": sql,
            "columns": result["columns"],
            "rows": store_rows,
            "row_count": result["row_count"],
            "truncated": result["truncated"],
        }
        cache_key = f"query:{turn_id}:{worker_id}:{query_id}"
        await redis.cache_set(cache_key, cache_payload, ttl=_QUERY_CACHE_TTL)
        logger.debug(
            "sql_cached",
            query_id=query_id,
            row_count=result["row_count"],
            truncated=result["truncated"],
        )

    return {
        "query_id": query_id,
        "columns": result["columns"],
        "preview_rows": result["rows"][:_PREVIEW_ROWS],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "error": result["error"],
    }


async def get_cached_query_result(
    turn_id: str,
    worker_id: str,
    query_id: str,
    redis: RedisService,
) -> dict[str, Any] | None:
    """
    Retrieve a previously cached query result for artifact promotion.
    Returns None if the cache entry has expired or never existed.
    """
    cache_key = f"query:{turn_id}:{worker_id}:{query_id}"
    return await redis.cache_get(cache_key)
