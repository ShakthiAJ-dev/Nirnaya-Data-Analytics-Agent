"""
app/websocket/sql_chat_agent/tools_worker.py
---------------------------------------------
LangChain tool definitions callable by artifact workers.

Worker tools:
  get_table_details          — same as orchestrator (for tables not pre-fetched)
  get_column_unique_values   — categorical lookup (metadata → DB fallback)
  fetch_business_rule        — full rule content
  run_sql                    — execute SELECT + cache result in Redis (returns query_id)
  finalize_kpi               — forced structured output: KPI card spec
  finalize_chart             — forced structured output: chart spec
  finalize_table             — forced structured output: table spec

Finalize tools use Pydantic models for input validation (schema enforcement).
The LLM MUST call exactly ONE finalize tool to complete its work.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from .sql_executor import run_sql_cached, run_sql_ephemeral

logger = get_logger(__name__)

_UNIQUE_VALUES_FALLBACK_CAP = 50


def _to_plain_dict(obj: Any) -> Any:
    """Recursively convert Pydantic models or containers to plain JSON-serializable Python types."""
    if hasattr(obj, "model_dump"):
        return _to_plain_dict(obj.model_dump())
    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        return _to_plain_dict(obj.dict())
    if isinstance(obj, dict):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain_dict(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Pydantic schemas for finalize tools (enforced structured output)
# ---------------------------------------------------------------------------

class KPIEncoding(BaseModel):
    value: float | int | None = None
    delta_pct: float | None = None
    target: float | None = None
    delta_abs: float | None = None


class FinalizeKPIInput(BaseModel):
    query_id: str = Field(description="The query_id returned by run_sql")
    title: str = Field(description="Short title for the KPI card, e.g. 'Total Revenue (Q1 2024)'")
    card_type: Literal["single_value", "value_with_delta", "value_with_target"] = Field(
        description="KPI card display type"
    )
    format: Literal["currency", "number", "percent"] = Field(
        description="Number formatting"
    )
    note: str = Field(description="One-line summary of what this number means and any important caveats")
    key_numbers: KPIEncoding = Field(description="The actual numeric values")


class ChartEncoding(BaseModel):
    x: str = Field(description="Field name for X axis")
    y: str = Field(description="Field name for Y axis (numeric metric)")
    series: Optional[str] = Field(None, description="Field for color grouping (cartesian_xy only)")
    size: Optional[str] = Field(None, description="Field for bubble size (bubble charts only)")
    category: Optional[str] = Field(None, description="Category field (part-to-whole charts)")
    value: Optional[str] = Field(None, description="Value field (part-to-whole / heatmap)")


class FinalizeChartInput(BaseModel):
    query_id: str = Field(description="The query_id returned by run_sql")
    title: str = Field(description="Descriptive chart title")
    chart_family: Literal[
        "cartesian_xy", "part_to_whole", "sequential_delta", "category_matrix", "flow_conversion"
    ] = Field(description="Chart family grouping")
    chart_type: Literal[
        "line", "bar", "grouped_bar", "stacked_bar", "area", "scatter", "bubble",
        "histogram", "box_plot", "donut", "waterfall", "heatmap", "funnel", "treemap"
    ] = Field(description="Specific chart type")
    encoding: ChartEncoding = Field(description="Axis / encoding field mappings")
    note: str = Field(description="One-line interpretation of the chart (key trend / insight)")
    key_numbers: dict = Field(description="Key summary numbers, e.g. {total: 48213.5, top_category: 'EU'}")


class TableColumnConfig(BaseModel):
    field: str = Field(description="Column field name from query result")
    label: str = Field(description="Human-readable display label")
    format: Optional[Literal["currency", "number", "percent", "date", None]] = None


class FinalizeTableInput(BaseModel):
    query_id: str = Field(description="The query_id returned by run_sql")
    title: str = Field(description="Descriptive table title")
    columns: list[TableColumnConfig] = Field(description="Column display configuration")
    note: str = Field(description="One-line summary of what this table shows")
    key_numbers: dict = Field(description="Key summary numbers, e.g. {row_count: 20}")


# ---------------------------------------------------------------------------
# Worker tool factory
# ---------------------------------------------------------------------------

def create_worker_tools(
    schema_name: str,
    full_metadata: dict,
    turn_id: str,
    worker_id: str,
    supabase_service: Any,
    redis_service: Any,
) -> list:
    """
    Factory: returns the list of tools available to a specific worker instance.
    Closes over schema_name, metadata, turn_id, worker_id, and services.
    """
    tables: dict = full_metadata.get("tables", {})
    business_rules: list[dict] = full_metadata.get("business_rules", [])

    # ------------------------------------------------------------------
    # Tool: get_table_details (same as orchestrator — workers may need it)
    # ------------------------------------------------------------------

    @tool
    async def get_table_details(table_names: list[str]) -> dict:
        """
        Get full schema and column details for one or more tables.
        Use this if you need information about tables not already provided
        in the prefetched context.

        NOTE: Unique-value *lists* for categorical columns are NOT included.
        Call get_column_unique_values() to get the actual list for a column.

        Args:
            table_names: List of table names (without schema prefix).
        Returns:
            Dict mapping table_name → {overview, grain, use_case, key_columns,
            domain_tags, key_notes, currency, timezone, row_count, columns[...]}.
        """
        result = {}
        for tname in table_names:
            if tname not in tables:
                result[tname] = {"error": f"Table '{tname}' not found."}
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
                if col.get("type_class") == "numeric" and col.get("min") is not None:
                    col_entry["min"] = col["min"]
                    col_entry["max"] = col["max"]
                    avg = col.get("avg")
                    col_entry["avg"] = round(avg, 2) if avg is not None else None
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
        Get unique values for a categorical column (text/enum).
        Served from metadata when pre-computed; falls back to a live DB query
        (capped at 50 values) for higher-cardinality columns.

        Args:
            table_name: Table name (without schema prefix).
            column_name: Column name.
        Returns:
            {"values": [...], "truncated": bool}
        """
        tinfo = tables.get(table_name, {})
        for col in tinfo.get("columns", []):
            if col["name"] == column_name:
                uv = col.get("unique_values")
                if uv is not None:
                    return {"values": uv, "truncated": False}
                # Live DB fallback
                sql = (
                    f"SELECT DISTINCT {column_name} FROM {schema_name}.{table_name} "
                    f"WHERE {column_name} IS NOT NULL "
                    f"ORDER BY {column_name} LIMIT {_UNIQUE_VALUES_FALLBACK_CAP + 1}"
                )
                results = await run_sql_ephemeral(
                    [{"sql": sql, "label": f"uv:{table_name}.{column_name}"}],
                    schema_name, supabase_service,
                )
                r = results[0]
                if r.get("error"):
                    return {"values": [], "truncated": False, "error": r["error"]}
                raw = [row.get(column_name) for row in r.get("rows", [])]
                return {"values": raw[:_UNIQUE_VALUES_FALLBACK_CAP], "truncated": len(raw) > _UNIQUE_VALUES_FALLBACK_CAP}
        return {"values": [], "truncated": False, "error": f"Column '{column_name}' not found."}

    # ------------------------------------------------------------------
    # Tool: fetch_business_rule
    # ------------------------------------------------------------------

    @tool
    async def fetch_business_rule(rule_ids: list[str]) -> dict:
        """
        Retrieve the full content of business rules by ID.
        Use when you need exact calculation logic or exclusion criteria.

        Args:
            rule_ids: List of rule ID strings.
        Returns:
            Dict mapping rule_id → {"title": ..., "content": ...}
        """
        result = {}
        for rule_id in rule_ids:
            for rule in business_rules:
                if rule.get("_id") == rule_id or rule.get("id") == rule_id:
                    result[rule_id] = {"title": rule.get("title", ""), "content": rule.get("content", "")}
                    break
            if rule_id not in result:
                result[rule_id] = {"error": f"Rule '{rule_id}' not found."}
        return result

    # ------------------------------------------------------------------
    # Tool: run_sql (CACHED — worker's primary query tool)
    # ------------------------------------------------------------------

    @tool
    async def run_sql(sql: str, label: str = "") -> dict:
        """
        Execute a SQL SELECT query. The result is cached in Redis under
        a unique query_id for later artifact promotion to Postgres.

        IMPORTANT:
        - Always use fully-qualified table names: {schema_name}.table_name
        - Do NOT use SET search_path
        - Results are capped at 5000 rows (full data cached for artifact)
        - The model receives a preview of 20 rows

        Args:
            sql:   The SELECT SQL statement.
            label: Short human-readable description (for logging).
        Returns:
            {
              "query_id": "uuid",      ← reference this in finalize_* tools
              "columns": [...],
              "preview_rows": [...],   ← first 20 rows (what you see)
              "row_count": int,        ← total rows returned
              "truncated": bool,       ← True if more than 5000 rows existed
              "error": str | None
            }
        """
        return await run_sql_cached(
            sql=sql,
            label=label,
            authorized_schema=schema_name,
            turn_id=turn_id,
            worker_id=worker_id,
            supabase=supabase_service,
            redis=redis_service,
        )

    # ------------------------------------------------------------------
    # Tool: finalize_kpi
    # ------------------------------------------------------------------

    @tool(args_schema=FinalizeKPIInput)
    async def finalize_kpi(
        query_id: str,
        title: str,
        card_type: str,
        format: str,
        note: str,
        key_numbers: Any,
    ) -> dict:
        """
        Finalize this worker's output as a KPI card artifact.
        Call this when your query produces a single metric value (revenue total,
        count, average, etc.). References the query_id from run_sql — do NOT
        restate the SQL here.

        card_type options:
          single_value      — just a number
          value_with_delta  — number + % change vs comparison period
          value_with_target — number + target value

        format options: currency | number | percent
        """
        return {
            "artifact_type": "kpi",
            "query_id": query_id,
            "title": title,
            "card_type": card_type,
            "format": format,
            "note": note,
            "key_numbers": _to_plain_dict(key_numbers),
        }

    # ------------------------------------------------------------------
    # Tool: finalize_chart
    # ------------------------------------------------------------------

    @tool(args_schema=FinalizeChartInput)
    async def finalize_chart(
        query_id: str,
        title: str,
        chart_family: str,
        chart_type: str,
        encoding: Any,
        note: str,
        key_numbers: Any,
    ) -> dict:
        """
        Finalize this worker's output as a chart artifact.
        References the query_id from run_sql — do NOT restate the SQL.

        chart_family → chart_type mappings:
          cartesian_xy      → line, bar, grouped_bar, stacked_bar, area, scatter, bubble, histogram, box_plot
          part_to_whole     → donut, treemap
          sequential_delta  → waterfall
          category_matrix   → heatmap
          flow_conversion   → funnel

        encoding fields (fill only what applies):
          x, y           — always required for cartesian_xy
          series         — optional grouping dimension (cartesian_xy)
          size           — bubble size field (bubble only)
          category, value — part-to-whole / category_matrix
        """
        return {
            "artifact_type": "chart",
            "query_id": query_id,
            "title": title,
            "chart_family": chart_family,
            "chart_type": chart_type,
            "encoding": _to_plain_dict(encoding),
            "note": note,
            "key_numbers": _to_plain_dict(key_numbers),
        }

    # ------------------------------------------------------------------
    # Tool: finalize_table
    # ------------------------------------------------------------------

    @tool(args_schema=FinalizeTableInput)
    async def finalize_table(
        query_id: str,
        title: str,
        columns: Any,
        note: str,
        key_numbers: Any,
    ) -> dict:
        """
        Finalize this worker's output as a data table artifact.
        References the query_id from run_sql — do NOT restate the SQL.

        columns: list of {field, label, format} objects.
          format options: currency | number | percent | date | null
        """
        return {
            "artifact_type": "table",
            "query_id": query_id,
            "title": title,
            "columns": _to_plain_dict(columns),
            "note": note,
            "key_numbers": _to_plain_dict(key_numbers),
        }

    return [
        get_table_details,
        get_column_unique_values,
        fetch_business_rule,
        run_sql,
        finalize_kpi,
        finalize_chart,
        finalize_table,
    ]
