"""
app/websocket/sql_chat_agent/state.py
--------------------------------------
LangGraph state TypedDicts for the orchestrator and worker graphs.

Design choices
──────────────
- Fields annotated with a reducer handle concurrent parallel-branch writes.
- Non-serialisable objects (WebSocket sender, services) NEVER go in state.
  They travel via RunnableConfig["configurable"] so the Postgres checkpointer
  can safely serialise/deserialise the state graph.

Conventions
───────────
  Annotated[T, add_messages]  → LangChain message list with append reducer
  Annotated[list, operator.add] → plain list with append reducer (parallel workers)
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class OrchestratorState(TypedDict):
    # ── Core identifiers ─────────────────────────────────────────────────
    chat_id: str
    turn_id: str
    session_id: str
    database_id: str
    schema_name: str          # e.g. n_abc123456789_mydb
    user_message: str

    # ── Conversation context ──────────────────────────────────────────────
    # Compacted last 3-5 turns: {role, markdown, artifact_titles}
    # Never includes full result_data.
    recent_turns: list[dict]

    # ── Metadata (loaded from Supabase Storage at turn start) ─────────────
    # tables_overview: name → {overview, key_columns, grain, domain_tags, …}
    tables_overview: dict
    # business_rules_index: [{_id, title}] — light index for discovery prompt
    business_rules_index: list[dict]
    # full_metadata: entire JSON blob — used by tools for deep lookups
    # Shape: {database_name, schema_name, tables: {...}, business_rules: [...]}
    full_metadata: dict

    # ── Discovery phase ───────────────────────────────────────────────────
    # add_messages reducer: appends AI + Tool messages without duplication
    discovery_messages: Annotated[list[BaseMessage], add_messages]
    discovery_iterations: int        # guard against infinite loops (max 8)
    # Side-effect accumulations from tool calls:
    fetched_table_details: dict      # table_name → full column details
    discovery_results: list[dict]    # run_discovery_queries results (NOT cached)

    # ── Decision phase ────────────────────────────────────────────────────
    decide_output: dict | None       # structured output from decide_node
    pending_question: dict | None    # set when ask_user is triggered
    dispatch_plan: list[dict] | None # artifact specs sent to workers

    # ── Artifact collection ───────────────────────────────────────────────
    # operator.add reducer: each parallel worker safely appends its result
    artifact_results: Annotated[list[dict], operator.add]

    # ── Final output ──────────────────────────────────────────────────────
    final_markdown: str | None
    follow_up_questions: list[str] | None


class WorkerState(TypedDict):
    # ── Identity ──────────────────────────────────────────────────────────
    turn_id: str
    worker_id: str                      # "0", "1", … "5"
    artifact_type: str                  # 'kpi' | 'chart' | 'table'
    chat_id: str
    database_id: str
    schema_name: str

    # ── Task spec from orchestrator ───────────────────────────────────────
    task_description: str               # what this artifact should answer
    metric_clarification: str           # shared definitions ALL artifacts must follow
    suggested_chart_type: str | None    # hint; worker may override
    tables_in_scope: list[str]
    relevant_business_rule_ids: list[str]

    # ── Pre-fetched context ───────────────────────────────────────────────
    # Orchestrator already resolved these; no redundant tool calls needed.
    prefetched_context: dict            # table_name → full column/stats details
    relevant_business_rules: list[dict] # [{_id, title, content}]

    # ── Worker LLM conversation ───────────────────────────────────────────
    worker_messages: Annotated[list[BaseMessage], add_messages]
    worker_iterations: int              # guard (max 6)

    # ── Query execution log ───────────────────────────────────────────────
    # Stored here so finalize_node can reference query_id without re-running SQL.
    # Full result_data lives in Redis under query:{turn_id}:{worker_id}:{query_id}
    executed_queries: list[dict]        # [{query_id, sql, row_count, truncated, error}]

    # ── Result ────────────────────────────────────────────────────────────
    finalized: dict | None              # output of finalize_kpi/chart/table tool


class ArtifactResult(TypedDict):
    """
    Compact summary returned from each worker to the orchestrator.
    Used by join_artifacts and synthesize_final.
    Full result_data lives in the Postgres artifacts row, not here.
    """
    artifact_id: str
    type: str                           # 'kpi' | 'chart' | 'table'
    title: str
    note: str                           # one-line summary (from finalize tool)
    key_numbers: dict[str, Any]         # e.g. {"value": 48213.5, "delta_pct": 12.4}
    status: str                         # 'fresh' | 'error'
    error_message: str | None
