"""
app/websocket/sql_chat_agent/prompts.py
-----------------------------------------
System prompt builders for orchestrator and worker LLM calls.

All prompts are built fresh per turn so they include current schema context
from the metadata blob. No prompt templates stored as static strings —
dynamic context is always injected.
"""

from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Utility: compact schema context for prompts
# ---------------------------------------------------------------------------

def _format_tables_for_prompt(full_metadata: dict, schema_name: str) -> str:
    """
    Render ALL tables from the metadata blob into a compact but complete
    text block for injection into LLM system prompts.

    Format per table:
      ## schema.table_name
      Overview: ...
      Grain: ...
      Key columns: col1, col2
      Business domain: tag1, tag2
      Notes: ...
      Columns:
        - col_name (type): [min=X, max=Y] [unique values: A, B, C]
    """
    tables = full_metadata.get("tables", {})
    if not tables:
        return "No tables found in metadata."

    lines: list[str] = []
    for tname, tinfo in tables.items():
        lines.append(f"\n## {schema_name}.{tname}")
        lines.append(f"Overview: {tinfo.get('overview', '')}")
        lines.append(f"Grain: {tinfo.get('grain', '')}")
        lines.append(f"Use case: {tinfo.get('use_case', '')}")
        kc = ", ".join(tinfo.get("key_columns", []))
        if kc:
            lines.append(f"Key columns: {kc}")
        tags = ", ".join(tinfo.get("domain_tags", []))
        if tags:
            lines.append(f"Domain: {tags}")
        notes = tinfo.get("key_notes", "")
        if notes:
            lines.append(f"Notes: {notes}")
        currency = tinfo.get("currency")
        if currency:
            lines.append(f"Currency: {currency}")
        tz = tinfo.get("timezone")
        if tz:
            lines.append(f"Timezone: {tz}")
        lines.append(f"Row count: {tinfo.get('row_count', '?')}")

        # Columns
        lines.append("Columns:")
        for col in tinfo.get("columns", []):
            col_name = col["name"]
            col_type = col.get("data_type", "")
            col_class = col.get("type_class", "")
            nullable = "nullable" if col.get("nullable") else "not null"
            parts = [f"  - {col_name} ({col_type} / {col_class}, {nullable})"]

            # Numeric stats
            if col_class == "numeric":
                mn = col.get("min")
                mx = col.get("max")
                av = col.get("avg")
                if mn is not None:
                    parts.append(f"min={mn}, max={mx}, avg={round(av, 2) if av else av}")

            # Categorical unique values (pre-computed, no DB round trip needed)
            uv = col.get("unique_values")
            if uv:
                shown = uv[:30]
                suffix = "…" if len(uv) > 30 else ""
                parts.append(f"values: [{', '.join(str(v) for v in shown)}{suffix}]")
            elif col.get("unique_values_count"):
                parts.append(f"~{col['unique_values_count']} distinct values")

            null_c = col.get("null_count", 0)
            if null_c:
                parts.append(f"nulls: {null_c}")

            lines.append("  ".join(parts))

    return "\n".join(lines)


def _format_business_rules_index(business_rules_index: list[dict]) -> str:
    if not business_rules_index:
        return "None defined."
    return "\n".join(
        f"  - {r.get('_id', r.get('id', '?'))}: {r.get('title', '')}"
        for r in business_rules_index
    )


def _format_recent_turns(recent_turns: list[dict]) -> str:
    if not recent_turns:
        return "No prior conversation."
    parts: list[str] = []
    for t in recent_turns:
        role = t.get("role", "?")
        if role == "user":
            parts.append(f"User: {t.get('content', {}).get('text', t.get('text', ''))}")
        else:
            md = t.get("content", {}).get("markdown", "")
            titles = t.get("artifact_titles", [])
            summary = md[:300] + ("…" if len(md) > 300 else "")
            artifacts_str = f" [Artifacts: {', '.join(titles)}]" if titles else ""
            parts.append(f"Assistant: {summary}{artifacts_str}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestrator system prompt
# ---------------------------------------------------------------------------

ORCHESTRATOR_SYSTEM_TEMPLATE = """You are Nirnaya, an expert data analytics AI assistant.
Your job is to answer the user's question about their dataset using the database schema below.

You operate in three phases:
1. DISCOVERY — Explore the schema to understand what data is available and how to answer the question.
2. DECIDE — Choose one of: (a) answer directly with text, (b) ask the user a clarifying question, or (c) dispatch artifact workers to produce charts/KPIs/tables.
3. SYNTHESIZE — After workers produce artifacts, write a concise analytical narrative.

━━━ DATABASE SCHEMA ━━━
Schema name: {schema_name}
All SQL must use fully-qualified table names: {schema_name}.table_name
{tables_context}

━━━ BUSINESS RULES ━━━
{business_rules_index}
Use fetch_business_rule(rule_ids=[...]) to retrieve the full content of any rule.

━━━ RECENT CONVERSATION ━━━
{recent_turns}

━━━ GROUND RULES ━━━
- NEVER use `SET search_path` — always use {schema_name}.table_name in all SQL.
- NEVER reference any schema other than {schema_name} in generated SQL.
- Do not hallucinate column names. Use only columns listed above.
- For ambiguous questions, ask ONE focused clarifying question before dispatching.
- If you run discovery queries, interpret the results carefully before deciding.
- When dispatching multiple artifacts, ensure they all use the SAME metric definitions via metric_clarification.
- Maximum 6 artifacts per response.
"""


def build_orchestrator_system_prompt(
    schema_name: str,
    full_metadata: dict,
    business_rules_index: list[dict],
    recent_turns: list[dict],
) -> str:
    return ORCHESTRATOR_SYSTEM_TEMPLATE.format(
        schema_name=schema_name,
        tables_context=_format_tables_for_prompt(full_metadata, schema_name),
        business_rules_index=_format_business_rules_index(business_rules_index),
        recent_turns=_format_recent_turns(recent_turns),
    )


# ---------------------------------------------------------------------------
# Worker system prompt
# ---------------------------------------------------------------------------

WORKER_SYSTEM_TEMPLATE = """You are a specialized data analytics SQL worker.
Your ONLY job is to write and execute SQL to produce a single {artifact_type} artifact.

━━━ YOUR TASK ━━━
{task_description}

━━━ METRIC DEFINITIONS (follow these exactly — consistency across all artifacts) ━━━
{metric_clarification}

━━━ DATABASE SCHEMA ━━━
Schema name: {schema_name}
All SQL must use: {schema_name}.table_name
{tables_context}

━━━ RELEVANT BUSINESS RULES ━━━
{business_rules}

━━━ AVAILABLE COLUMNS (pre-fetched) ━━━
{prefetched_context}

━━━ RULES ━━━
- Use ONLY the schema {schema_name}. Never reference other schemas.
- Write clean, efficient SQL. Use LIMIT where appropriate for speed.
- After getting query results, call the appropriate finalize tool:
  * finalize_kpi     — for a single number / metric card
  * finalize_chart   — for a visualization
  * finalize_table   — for a data table
- Reference the query_id from run_sql — do NOT restate the full SQL in finalize.
- You MUST call a finalize tool to complete your task. Do not just explain.
{chart_hint}
"""


def build_worker_system_prompt(
    artifact_type: str,
    task_description: str,
    metric_clarification: str,
    schema_name: str,
    full_metadata: dict,
    prefetched_context: dict,
    relevant_business_rules: list[dict],
    suggested_chart_type: str | None,
    tables_in_scope: list[str],
) -> str:
    # Only show tables in scope (plus a compact view of all for joins)
    scoped_meta = {"tables": {}}
    for tname in tables_in_scope:
        if tname in full_metadata.get("tables", {}):
            scoped_meta["tables"][tname] = full_metadata["tables"][tname]

    # Fall back to full schema if scope is empty
    if not scoped_meta["tables"]:
        scoped_meta = full_metadata

    tables_context = _format_tables_for_prompt(scoped_meta, schema_name)

    # Business rules content (full text)
    if relevant_business_rules:
        br_text = "\n".join(
            f"  [{r.get('_id', '?')}] {r.get('title', '')}: {r.get('content', '')}"
            for r in relevant_business_rules
        )
    else:
        br_text = "None specified for this artifact."

    # Prefetched context (column details already fetched by orchestrator)
    if prefetched_context:
        pc_lines = []
        for tname, tinfo in prefetched_context.items():
            pc_lines.append(f"Table {schema_name}.{tname}:")
            for col in tinfo.get("columns", []):
                pc_lines.append(f"  - {col['name']} ({col.get('data_type', '')})")
        prefetched_str = "\n".join(pc_lines)
    else:
        prefetched_str = "See schema above."

    chart_hint = ""
    if artifact_type == "chart" and suggested_chart_type:
        chart_hint = f"\nSuggested chart type: {suggested_chart_type} (you may override if data fits a different type better)."

    return WORKER_SYSTEM_TEMPLATE.format(
        artifact_type=artifact_type.upper(),
        task_description=task_description,
        metric_clarification=metric_clarification,
        schema_name=schema_name,
        tables_context=tables_context,
        business_rules=br_text,
        prefetched_context=prefetched_str,
        chart_hint=chart_hint,
    )


# ---------------------------------------------------------------------------
# Decide-node forced structured output prompt
# ---------------------------------------------------------------------------

DECIDE_SYSTEM = """You are a routing agent. Given the user's question and the discovery findings,
choose exactly ONE action:

  direct_response  — The question can be answered in plain text (no data needed, or already answered by discovery).
  ask_user         — The question is ambiguous and you need ONE specific clarification before proceeding.
  dispatch_artifacts — Dispatch workers to produce kpi/chart/table artifacts.

Return ONLY valid JSON matching the schema provided. Do not add explanation outside the JSON.
"""


# ---------------------------------------------------------------------------
# Synthesize-final forced structured output prompt
# ---------------------------------------------------------------------------

SYNTHESIZE_SYSTEM = """You are an analytics narrative writer.
Given the artifact results below, write a concise markdown summary (2-4 paragraphs) that:
1. Directly answers the user's original question
2. Highlights the most important numbers from key_numbers
3. Notes any partial failures (artifacts with status='error') honestly
4. Does NOT repeat raw data already in the artifacts

Also generate exactly 2-3 follow-up questions that would naturally extend this analysis.

Return ONLY valid JSON: {"markdown": "...", "follow_up_questions": ["...", "...", "..."]}
"""
