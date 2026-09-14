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

# ── KPI ─────────────────────────────────────────────────────────────────────

class KPINumbers(BaseModel):
    """
    Strict key_numbers shape — fill only the fields that match your card_type:

      card_type = 'single_value':
        • value       (required) — the single metric number

      card_type = 'value_with_delta':
        • value       (required) — current period value
        • delta_pct   (required) — % change vs comparison period (signed: +5.2 = +5.2%)
        • delta_abs   (optional) — absolute change (same unit as value)

      card_type = 'value_with_target':
        • value       (required) — current / actual value
        • target      (required) — the target / goal value
        • delta_pct   (optional) — ((value - target) / target) * 100 (signed)

    Never mix in extra keys — the FE renders strictly based on card_type.
    """
    value:     float | int | None = None   # always required
    delta_pct: float | None = None          # value_with_delta (required) / value_with_target (optional)
    delta_abs: float | None = None          # value_with_delta (optional)
    target:    float | None = None          # value_with_target (required)


class KPIDisplayConfig(BaseModel):
    """
    Optional display hints the FE uses to format the KPI card.
    The LLM SHOULD always populate these — they make the UI look professional.
    """
    prefix:            Optional[str] = None   # e.g. "$", "€", "£"  (currency KPIs)
    suffix:            Optional[str] = None   # e.g. "%", "K", "M", "B"  (when format="percent" or large numbers)
    decimal_places:    int = 2                # digits after decimal point (0 for counts/integers)
    trend_direction:   Optional[Literal["up_is_good", "down_is_good"]] = "up_is_good"
    # "up_is_good"   → positive delta_pct rendered green, negative red   (revenue, NPS, etc.)
    # "down_is_good" → positive delta_pct rendered red, negative green   (cost, churn, errors, etc.)
    comparison_label:  Optional[str] = None   # e.g. "vs last month", "vs Q1 2023"
    color_theme:       Optional[Literal["default", "positive", "negative", "warning"]] = "default"
    # "default"  — neutral accent colour
    # "positive" — green accent (e.g. revenue KPI confirmed above target)
    # "negative" — red accent   (e.g. churn KPI above threshold)
    # "warning"  — amber accent (e.g. metric approaching threshold)


class FinalizeKPIInput(BaseModel):
    query_id:       str = Field(description="The query_id returned by run_sql")
    title:          str = Field(description="Short title, e.g. 'Total Revenue (Q1 2024)'")
    card_type:      Literal["single_value", "value_with_delta", "value_with_target"] = Field(
        description=(
            "single_value      — one number only\n"
            "value_with_delta  — number + % change vs comparison period\n"
            "value_with_target — number + target / goal value"
        )
    )
    format:         Literal["currency", "number", "percent"] = Field(
        description=(
            "currency — prefix '$' (or from table metadata); right-align\n"
            "number   — plain numeric; right-align\n"
            "percent  — suffix '%'; right-align"
        )
    )
    note:           str = Field(description="One-line summary of what this number means and any caveats")
    key_numbers:    KPINumbers = Field(
        description=(
            "Fill ONLY the fields matching your card_type:\n"
            "  single_value       → value only\n"
            "  value_with_delta   → value + delta_pct (required) + delta_abs (optional)\n"
            "  value_with_target  → value + target (required) + delta_pct (optional)"
        )
    )
    display_config: Optional[KPIDisplayConfig] = Field(
        None,
        description=(
            "Display hints for the FE renderer. Always populate:\n"
            "  prefix  — '$' for currency, '' otherwise\n"
            "  suffix  — '%' for percent KPIs, 'K'/'M'/'B' for large numbers\n"
            "  decimal_places — 0 for counts/integers, 2 for currency/ratios\n"
            "  trend_direction — 'up_is_good' (revenue/NPS) or 'down_is_good' (costs/errors)\n"
            "  comparison_label — describe the comparison period if applicable\n"
            "  color_theme — 'default' unless you know this KPI is in a good/bad state"
        )
    )


# ── Chart ────────────────────────────────────────────────────────────────────

class ChartEncoding(BaseModel):
    """
    Fill ONLY the fields that apply to your chart_family and chart_type.

    cartesian_xy (line, bar, area, scatter, histogram, box_plot):
      x (required) + y (required) + series (optional grouping dimension)

    cartesian_xy (grouped_bar, stacked_bar):
      x (required) + y (required) + series (REQUIRED — the grouping field)

    cartesian_xy (bubble):
      x (required) + y (required) + size (REQUIRED — numeric bubble size field)

    part_to_whole (donut, treemap):
      category (required) + value (required)
      x and y must be null/omitted.

    sequential_delta (waterfall):
      x (required — category/label column) + y (required — signed numeric delta or absolute)

    category_matrix (heatmap):
      x (required — row labels) + y (required — column labels) + value (required — cell numeric value)

    flow_conversion (funnel):
      category (required — stage name) + value (required — count/rate per stage)
    """
    x:        Optional[str] = Field(None, description="X-axis field name (cartesian families)")
    y:        Optional[str] = Field(None, description="Y-axis field name (numeric metric)")
    series:   Optional[str] = Field(None, description="Grouping/color dimension (grouped_bar, stacked_bar, optional for others)")
    size:     Optional[str] = Field(None, description="Bubble size field (bubble charts only)")
    category: Optional[str] = Field(None, description="Category label field (donut, treemap, funnel)")
    value:    Optional[str] = Field(None, description="Value field (part-to-whole / heatmap / funnel)")


class ChartConfig(BaseModel):
    """
    Optional display-level hints the FE uses to render the chart.
    Defaults are listed — only override when the data or chart type warrants it.
    """
    orientation:      Optional[Literal["vertical", "horizontal"]] = "vertical"
    # "horizontal" useful for bar charts with long category labels
    show_legend:      bool = True
    # False only when chart has a single series or data is self-explanatory
    show_data_labels: bool = False
    # True for donut slices, bar charts with ≤10 bars, waterfall steps
    show_grid:        bool = True
    sort_order:       Optional[Literal["asc", "desc", "none"]] = "none"
    # Applies to bar, donut, funnel: "desc" to rank categories by value
    stack_type:       Optional[Literal["value", "percent"]] = "value"
    # stacked_bar only: "percent" for 100% stacked view
    line_style:       Optional[Literal["solid", "dashed", "dotted"]] = "solid"
    # line charts only
    fill_opacity:     Optional[float] = None
    # area charts: 0.1–0.4 is typical
    x_axis_label:     Optional[str] = None   # override auto-generated label
    y_axis_label:     Optional[str] = None   # override auto-generated label


class FinalizeChartInput(BaseModel):
    query_id:     str = Field(description="The query_id returned by run_sql")
    title:        str = Field(description="Descriptive chart title")
    chart_family: Literal[
        "cartesian_xy", "part_to_whole", "sequential_delta", "category_matrix", "flow_conversion"
    ] = Field(
        description=(
            "cartesian_xy      — line, bar, grouped_bar, stacked_bar, area, scatter, bubble, histogram, box_plot\n"
            "part_to_whole     — donut, treemap\n"
            "sequential_delta  — waterfall\n"
            "category_matrix   — heatmap\n"
            "flow_conversion   — funnel"
        )
    )
    chart_type:   Literal[
        "line", "bar", "grouped_bar", "stacked_bar", "area", "scatter", "bubble",
        "histogram", "box_plot", "donut", "waterfall", "heatmap", "funnel", "treemap"
    ] = Field(
        description=(
            "Must be consistent with chart_family:\n"
            "  cartesian_xy      → line | bar | grouped_bar | stacked_bar | area | scatter | bubble | histogram | box_plot\n"
            "  part_to_whole     → donut | treemap\n"
            "  sequential_delta  → waterfall\n"
            "  category_matrix   → heatmap\n"
            "  flow_conversion   → funnel"
        )
    )
    encoding:     ChartEncoding = Field(description="Axis / encoding field mappings — see ChartEncoding rules")
    note:         str = Field(description="One-line key trend / insight (e.g. 'EU drives 43% of total revenue')")
    key_numbers:  dict = Field(
        description=(
            "Most important summary numbers from the data for the narrative.\n"
            "Examples: {\"total\": 48213.5, \"top_category\": \"EU\", \"period\": \"Q1 2024\", \"pct_of_total\": 43.2}"
        )
    )
    chart_config: Optional[ChartConfig] = Field(
        None,
        description=(
            "Optional display hints. Key ones to set:\n"
            "  orientation     — 'horizontal' for bar with long category names\n"
            "  sort_order      — 'desc' to rank bar / donut categories\n"
            "  show_data_labels — True for donut, small bar charts\n"
            "  stack_type      — 'percent' for 100%% stacked bars\n"
            "  fill_opacity    — 0.15-0.4 for area charts\n"
            "  x_axis_label / y_axis_label — human-readable axis labels"
        )
    )


# ── Table ────────────────────────────────────────────────────────────────────

class TableColumnConfig(BaseModel):
    """Column display configuration for a single table column."""
    field:      str = Field(description="Column field name exactly as it appears in query result")
    label:      str = Field(description="Human-readable display label (Title Case)")
    format:     Optional[Literal["currency", "number", "percent", "date"]] = Field(
        None,
        description=(
            "currency — right-align, prefix '$' (or currency symbol from metadata)\n"
            "number   — right-align, apply decimal_places\n"
            "percent  — right-align, suffix '%%'\n"
            "date     — center-align, format as locale date\n"
            "null     — left-align, plain text (default for text/id columns)"
        )
    )
    align:      Optional[Literal["left", "center", "right"]] = Field(
        None,
        description=(
            "Column text alignment. Auto-defaults:\n"
            "  left   — text, id, name columns (format=null)\n"
            "  right  — numeric columns (format=currency/number/percent)\n"
            "  center — date columns (format=date)\n"
            "Only set explicitly to override the auto-default."
        )
    )
    sortable:   bool = Field(True, description="Whether the FE allows sorting by this column")
    width_hint: Optional[Literal["xs", "sm", "md", "lg", "xl"]] = Field(
        None,
        description=(
            "Relative column width hint for the FE table renderer:\n"
            "  xs — id/flag columns (~60px)\n"
            "  sm — short numeric / code columns (~100px)\n"
            "  md — typical label / amount columns (~160px, default)\n"
            "  lg — longer description fields (~240px)\n"
            "  xl — full-text / URL columns (~360px)\n"
            "Omit to let the FE auto-size."
        )
    )


class TableConfig(BaseModel):
    """Table-level display settings."""
    default_sort_column:    Optional[str] = Field(
        None, description="Field name to sort by on initial render (must match a column field)"
    )
    default_sort_direction: Optional[Literal["asc", "desc"]] = Field(
        "desc", description="Initial sort direction"
    )
    show_row_numbers:       bool = Field(False, description="Show a leading row-number column")
    enable_search:          bool = Field(False, description="Show a search/filter input above the table")
    page_size:              Optional[int] = Field(
        None, description="Rows per page for pagination; null = show all rows (up to result_data cap)"
    )


class FinalizeTableInput(BaseModel):
    query_id:     str = Field(description="The query_id returned by run_sql")
    title:        str = Field(description="Descriptive table title")
    columns:      list[TableColumnConfig] = Field(
        description=(
            "Column display configuration — one entry per column in the query result.\n"
            "Column order here controls the display order in the FE table.\n"
            "Rules:\n"
            "  • Always include all columns that matter; omit internal/redundant columns.\n"
            "  • Set format=currency for money fields, format=percent for rate fields.\n"
            "  • Set align only to override auto-defaults.\n"
            "  • Set width_hint for id columns (xs) and description columns (lg/xl)."
        )
    )
    note:         str = Field(description="One-line summary of what this table shows")
    key_numbers:  dict = Field(
        description=(
            "Key summary numbers for the narrative.\n"
            "Example: {\"row_count\": 20, \"total_revenue\": 482130.5, \"date_range\": \"Jan-Mar 2024\"}"
        )
    )
    table_config: Optional[TableConfig] = Field(
        None,
        description=(
            "Optional table-level display settings:\n"
            "  default_sort_column    — the most analytically relevant sort field\n"
            "  default_sort_direction — 'desc' to show largest values first\n"
            "  show_row_numbers       — True for ranked/leaderboard tables\n"
            "  enable_search          — True for large reference tables\n"
            "  page_size              — set if row count > 50 to paginate"
        )
    )




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
        display_config: Any = None,
    ) -> dict:
        """
        Finalize this worker's output as a KPI card artifact.
        Call this when your query produces a single metric value (revenue total,
        count, average, etc.). References the query_id from run_sql — do NOT
        restate the SQL here.

        card_type options:
          single_value      — just a number; key_numbers = {value}
          value_with_delta  — number + % change; key_numbers = {value, delta_pct, delta_abs?}
          value_with_target — number + goal; key_numbers = {value, target, delta_pct?}

        format options: currency | number | percent

        display_config: Always populate for professional UI rendering:
          prefix, suffix, decimal_places, trend_direction, comparison_label, color_theme
        """
        return {
            "artifact_type":  "kpi",
            "query_id":       query_id,
            "title":          title,
            "card_type":      card_type,
            "format":         format,
            "note":           note,
            "key_numbers":    _to_plain_dict(key_numbers),
            "display_config": _to_plain_dict(display_config) if display_config else {},
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
        chart_config: Any = None,
    ) -> dict:
        """
        Finalize this worker's output as a chart artifact.
        References the query_id from run_sql — do NOT restate the SQL.

        chart_family → chart_type mappings (MUST be consistent):
          cartesian_xy      → line | bar | grouped_bar | stacked_bar | area | scatter | bubble | histogram | box_plot
          part_to_whole     → donut | treemap
          sequential_delta  → waterfall
          category_matrix   → heatmap
          flow_conversion   → funnel

        encoding — fill ONLY fields for your chart type (see ChartEncoding docstring):
          cartesian_xy:     x + y required; series optional; series REQUIRED for grouped/stacked
          bubble:           x + y + size required
          part_to_whole:    category + value required (no x/y)
          waterfall:        x + y required
          heatmap:          x + y + value required
          funnel:           category + value required (no x/y)

        chart_config — display hints (orientation, sort_order, show_data_labels, etc.)
        """
        return {
            "artifact_type": "chart",
            "query_id":      query_id,
            "title":         title,
            "chart_family":  chart_family,
            "chart_type":    chart_type,
            "encoding":      _to_plain_dict(encoding),
            "note":          note,
            "key_numbers":   _to_plain_dict(key_numbers),
            "chart_config":  _to_plain_dict(chart_config) if chart_config else {},
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
        table_config: Any = None,
    ) -> dict:
        """
        Finalize this worker's output as a data table artifact.
        References the query_id from run_sql — do NOT restate the SQL.

        columns: list of {field, label, format, align, sortable, width_hint} objects.
          format options: currency | number | percent | date | null
          align: auto-defaults by format; only set to override
          width_hint: xs | sm | md | lg | xl (relative width)

        table_config: table-level settings (default_sort_column, show_row_numbers, etc.)
        """
        return {
            "artifact_type":  "table",
            "query_id":       query_id,
            "title":          title,
            "columns":        _to_plain_dict(columns),
            "note":           note,
            "key_numbers":    _to_plain_dict(key_numbers),
            "table_config":   _to_plain_dict(table_config) if table_config else {},
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
