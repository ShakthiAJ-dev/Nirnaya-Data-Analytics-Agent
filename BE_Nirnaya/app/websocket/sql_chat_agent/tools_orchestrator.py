"""
app/websocket/sql_chat_agent/tools_orchestrator.py
----------------------------------------------------
LangChain tool definitions callable by the orchestrator's discovery_loop.

Tool pattern
────────────
Each tool is a factory function that closes over the current state and
services (passed as a context dict). This avoids putting non-serialisable
objects in the LangGraph state and avoids global singletons.

Orchestrator tools (NO SQL caching):
  get_table_details          — deep column info from metadata blob
  get_column_unique_values   — categorical value list from metadata (or DB fallback)
  run_discovery_queries      — run SELECT(s), return inline results (NOT cached)
  fetch_business_rule        — fetch full rule content from metadata
  signal_ready_to_decide     — no-op; tells routing function to exit discovery loop
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from app.core.logging import get_logger
from .sql_executor import run_sql_ephemeral

logger = get_logger(__name__)

_UNIQUE_VALUES_FALLBACK_CAP = 50   # max values returned by DB fallback


def create_orchestrator_tools(
    schema_name: str,
    full_metadata: dict,
    supabase_service: Any,          # SupabaseService — not typed to avoid circular import
) -> list:
    """
    Factory: returns a list of bound LangChain tools for the orchestrator.
    Call once per turn, passing the current state's schema_name + full_metadata.
    """
    tables: dict = full_metadata.get("tables", {})
    business_rules: list[dict] = full_metadata.get("business_rules", [])

    # ------------------------------------------------------------------
    # Tool: get_table_details
    # ------------------------------------------------------------------

    @tool
    async def get_table_details(table_names: list[str]) -> dict:
        """
        Get detailed schema information for one or more tables, including all
        column names, data types, nullability, numeric stats (min/max/avg for
        numeric columns), and distinct-value counts for categorical columns.

        NOTE: Unique-value *lists* for categorical columns are NOT included here
        to keep the response compact. Call get_column_unique_values() to get
        the actual list of values for a specific column.

        Use this tool before writing any SQL — the system-prompt schema shows
        only table overviews, not individual columns.

        Args:
            table_names: List of table names (without schema prefix).
        Returns:
            Dict mapping table_name → {overview, grain, use_case, key_columns,
            domain_tags, key_notes, currency, timezone, row_count, columns[...]}.
        """
        result = {}
        for tname in table_names:
            if tname not in tables:
                result[tname] = {"error": f"Table '{tname}' not found in metadata."}
                continue
            tinfo = tables[tname]
            detail: dict = {
                "overview":    tinfo.get("overview", ""),
                "grain":       tinfo.get("grain", ""),
                "use_case":    tinfo.get("use_case", ""),
                "key_columns": tinfo.get("key_columns", []),
                "domain_tags": tinfo.get("domain_tags", []),
                "key_notes":   tinfo.get("key_notes", ""),
                "currency":    tinfo.get("currency"),
                "timezone":    tinfo.get("timezone"),
                "row_count":   tinfo.get("row_count"),
                "columns":     [],
            }
            for col in tinfo.get("columns", []):
                col_entry: dict = {
                    "name":       col["name"],
                    "data_type":  col.get("data_type", ""),
                    "type_class": col.get("type_class", ""),
                    "nullable":   col.get("nullable", True),
                }
                # Numeric stats
                if col.get("type_class") == "numeric" and col.get("min") is not None:
                    col_entry["min"] = col["min"]
                    col_entry["max"] = col["max"]
                    avg = col.get("avg")
                    col_entry["avg"] = round(avg, 2) if avg is not None else None
                # Distinct count (not the list) for categorical columns
                uvc = col.get("unique_values_count")
                if uvc:
                    col_entry["unique_values_count"] = uvc
                null_c = col.get("null_count")
                if null_c:
                    col_entry["null_count"] = null_c
                detail["columns"].append(col_entry)
            result[tname] = detail
        return result


    # ------------------------------------------------------------------
    # Tool: get_column_unique_values
    # ------------------------------------------------------------------

    @tool
    async def get_column_unique_values(table_name: str, column_name: str) -> dict:
        """
        Get the list of unique values for a categorical (text/enum) column.
        For columns with fewer than 50 distinct values, this is served from
        the pre-computed metadata (fast, no DB call). For columns with more
        distinct values, a live DB query is run (capped at 50).

        Only useful for string/categorical columns — not numeric or datetime.

        Args:
            table_name: Table name (without schema prefix).
            column_name: Column name to get unique values for.
        Returns:
            {"values": [...], "truncated": bool}
        """
        tinfo = tables.get(table_name, {})
        if not tinfo:
            return {"values": [], "truncated": False, "error": f"Table '{table_name}' not found."}

        for col in tinfo.get("columns", []):
            if col["name"] == column_name:
                # Pre-computed unique values (most text columns with <50 distinct)
                uv = col.get("unique_values")
                if uv is not None:
                    return {"values": uv, "truncated": False}

                # Fallback: live DB query (for columns without pre-computed list)
                sql = (
                    f"SELECT DISTINCT {column_name} FROM {schema_name}.{table_name} "
                    f"WHERE {column_name} IS NOT NULL "
                    f"ORDER BY {column_name} LIMIT {_UNIQUE_VALUES_FALLBACK_CAP + 1}"
                )
                results = await run_sql_ephemeral(
                    [{"sql": sql, "label": f"unique_values:{table_name}.{column_name}"}],
                    schema_name,
                    supabase_service,
                )
                r = results[0]
                if r.get("error"):
                    return {"values": [], "truncated": False, "error": r["error"]}

                raw_values = [row.get(column_name) for row in r.get("rows", [])]
                truncated = len(raw_values) > _UNIQUE_VALUES_FALLBACK_CAP
                return {"values": raw_values[:_UNIQUE_VALUES_FALLBACK_CAP], "truncated": truncated}

        return {"values": [], "truncated": False, "error": f"Column '{column_name}' not found in '{table_name}'."}

    # ------------------------------------------------------------------
    # Tool: run_discovery_queries
    # ------------------------------------------------------------------

    @tool
    async def run_discovery_queries(
        queries: list[dict],
        max_concurrent: int = 5,
    ) -> list[dict]:
        """
        Run one or more SQL SELECT queries to explore the data.
        Results are returned INLINE — not stored in Redis.
        Use this to understand distributions, ranges, or relationships
        before deciding what artifacts to build.

        IMPORTANT: Always use fully-qualified table names: {schema_name}.table_name

        Args:
            queries: List of {{"sql": "SELECT ...", "label": "human label"}} dicts.
            max_concurrent: Max parallel queries (default 5).
        Returns:
            List of {{label, query_id, columns, preview_rows, row_count, truncated, error}}
        """
        return await run_sql_ephemeral(
            queries,
            schema_name,
            supabase_service,
            max_concurrent=min(max_concurrent, 5),
        )

    # ------------------------------------------------------------------
    # Tool: fetch_business_rule
    # ------------------------------------------------------------------

    @tool
    async def fetch_business_rule(rule_ids: list[str]) -> dict:
        """
        Retrieve the full content of one or more business rules by their ID.
        Business rule IDs are listed in the system prompt (e.g. BR_1_abc123).
        Use this when a rule's title suggests it's relevant to the current question.

        Args:
            rule_ids: List of rule ID strings.
        Returns:
            Dict mapping rule_id → {{"title": ..., "content": ...}}
        """
        result = {}
        for rule_id in rule_ids:
            for rule in business_rules:
                if rule.get("_id") == rule_id or rule.get("id") == rule_id:
                    result[rule_id] = {
                        "title": rule.get("title", ""),
                        "content": rule.get("content", ""),
                    }
                    break
            if rule_id not in result:
                result[rule_id] = {"error": f"Rule '{rule_id}' not found."}
        return result

    # ------------------------------------------------------------------
    # Tool: signal_ready_to_decide
    # ------------------------------------------------------------------

    @tool
    async def signal_ready_to_decide(reason: str = "") -> dict:
        """
        Call this when you have gathered enough information and are ready to
        make a decision (direct answer, ask user, or dispatch artifacts).
        Do not call any more discovery tools after calling this.

        Args:
            reason: Brief explanation of what you've learned (optional).
        Returns:
            {{"status": "ready"}}
        """
        return {"status": "ready", "reason": reason}

    return [
        get_table_details,
        get_column_unique_values,
        run_discovery_queries,
        fetch_business_rule,
        signal_ready_to_decide,
    ]
