"""
app/websocket/sql_chat_agent/worker_graph.py
---------------------------------------------
Worker logic: the async function that runs for each artifact spec dispatched
by the orchestrator via Send.

Architecture
────────────
Each worker instance:
  1. Loads prefetched context from the state it received via Send
  2. Runs an explore_loop (LLM + tools) to write and execute SQL
  3. Calls a finalize tool (finalize_kpi / finalize_chart / finalize_table)
  4. Promotes the cached query result to a Postgres artifacts row
  5. Returns an ArtifactResult dict back to the orchestrator state

The worker is implemented as a plain async function (not a compiled StateGraph)
to keep things simple. The orchestrator's run_worker_node calls this function
and appends the result to orchestrator state via the operator.add reducer.

Max iterations: 6 (prevents infinite loops on bad SQL)
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.core.logging import get_logger
from .events import StepName, make_step
from .prompts import build_worker_system_prompt
from .sql_executor import get_cached_query_result
from .tools_worker import create_worker_tools

logger = get_logger(__name__)

_MAX_WORKER_ITERATIONS = 6


# ---------------------------------------------------------------------------
# Promote artifact: Redis cache → Postgres artifacts row
# ---------------------------------------------------------------------------

async def _promote_artifact(
    *,
    finalized: dict,
    worker_state: dict,
    query_result: dict,
    effective_db_id: str | None,
    supabase_service: Any,
    chat_service: Any,
) -> str:
    """Write the finalized artifact to Postgres artifacts table. Returns artifact_id."""
    artifact_type = finalized.get("artifact_type", "table")

    config: dict[str, Any] = {}
    if artifact_type == "chart":
        config = {
            "chart_family": finalized.get("chart_family"),
            "chart_type":   finalized.get("chart_type"),
            "encoding":     finalized.get("encoding"),
        }
    elif artifact_type == "kpi":
        config = {
            "card_type": finalized.get("card_type"),
            "format":    finalized.get("format"),
        }
    elif artifact_type == "table":
        config = {"columns": finalized.get("columns", [])}

    result_rows: list[dict] = query_result.get("rows", [])

    artifact_row = await chat_service.create_artifact(
        database_id=effective_db_id,
        chat_id=worker_state["chat_id"],
        message_id=None,
        artifact_type=artifact_type,
        title=finalized.get("title", "Untitled"),
        sql_query=query_result.get("sql", ""),
        config=config,
        result_data=result_rows,
        row_count=query_result.get("row_count", len(result_rows)),
        status="fresh",
    )
    return artifact_row["id"]


# ---------------------------------------------------------------------------
# Main worker function
# ---------------------------------------------------------------------------

async def run_worker(
    worker_state: dict,
    config: RunnableConfig,
) -> dict:
    """
    Execute the full worker pipeline for one artifact spec.

    Returns a dict with the single key "artifact_results" containing
    a list with one ArtifactResult — compatible with the orchestrator's
    operator.add reducer.
    """
    cfg = config.get("configurable", {})
    llm_service = cfg["llm_service"]
    supabase_service = cfg["supabase_service"]
    redis_service = cfg["redis_service"]
    chat_service = cfg["chat_service"]
    ws_send = cfg["ws_send"]
    seq_counter = cfg["seq_counter"]
    # None for demo database (no FK row), UUID string for real databases
    effective_db_id: str | None = cfg.get("effective_db_id", worker_state.get("database_id"))

    turn_id = worker_state["turn_id"]
    worker_id = worker_state["worker_id"]
    chat_id = worker_state["chat_id"]
    artifact_type = worker_state["artifact_type"]
    model: str = cfg.get("model", "claude-4.5-haiku")
    provider: str | None = cfg.get("provider")

    # ── Emit: worker starting ──────────────────────────────────────────
    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=chat_id,
        turn_id=turn_id,
        seq=seq,
        name=StepName.ARTIFACT_PROGRESS,
        status="in_progress",
        title=f"Building {artifact_type.upper()} — Worker {worker_id}",
        detail=worker_state["task_description"],
        reasoning=f"Metric scope: {worker_state['metric_clarification'][:200]}",
        worker_id=worker_id,
    ))

    # ── Build tools for this worker instance ─────────────────────────
    schema_name = worker_state["schema_name"]
    full_metadata = cfg["full_metadata"]

    worker_tools = create_worker_tools(
        schema_name=schema_name,
        full_metadata=full_metadata,
        turn_id=turn_id,
        worker_id=worker_id,
        supabase_service=supabase_service,
        redis_service=redis_service,
    )
    tool_map = {t.name: t for t in worker_tools}

    # ── No pre-built LLM — will use llm_service.ainvoke(tools=...) per iteration ──
    # This keeps the worker model-agnostic (uses whatever model FE selected).

    # ── Build initial messages ────────────────────────────────────────
    system_prompt = build_worker_system_prompt(
        artifact_type=artifact_type,
        task_description=worker_state["task_description"],
        metric_clarification=worker_state["metric_clarification"],
        schema_name=schema_name,
        full_metadata=full_metadata,
        prefetched_context=worker_state.get("prefetched_context", {}),
        relevant_business_rules=worker_state.get("relevant_business_rules", []),
        suggested_chart_type=worker_state.get("suggested_chart_type"),
        tables_in_scope=worker_state.get("tables_in_scope", []),
    )

    messages: list = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            f"Please build the {artifact_type} artifact as described.\n"
            f"Task: {worker_state['task_description']}\n"
            f"Metric definitions: {worker_state['metric_clarification']}"
        )),
    ]

    finalized_result: dict | None = None
    executed_queries: list[dict] = []

    # ── Explore loop ─────────────────────────────────────────────────
    for iteration in range(_MAX_WORKER_ITERATIONS):
        try:
            response: AIMessage = await llm_service.ainvoke(
                messages,
                model=model,
                tools=worker_tools,
                max_tokens=4096,
                temperature=0.2,
                provider=provider,
            )
        except Exception as exc:
            logger.warning("worker_llm_error", worker_id=worker_id, iteration=iteration, error=str(exc))
            return _error_result(worker_state, f"LLM call failed: {exc}")

        messages.append(response)

        # Check if model wants to call tools
        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls:
            # Model produced text without calling any tool — shouldn't happen but handle gracefully
            logger.warning("worker_no_tool_call", worker_id=worker_id, iteration=iteration)
            if iteration == 0:
                # First iteration with no tool call: likely confused, give a nudge
                messages.append(HumanMessage(content=(
                    "You must call run_sql first, then call finalize_kpi, finalize_chart, or finalize_table. "
                    "Do not produce a text response — use the tools."
                )))
                continue
            break

        # Execute all tool calls in this response
        tool_results: list[ToolMessage] = []
        hit_finalize = False

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_call_id = tc["id"]

            if tool_name.startswith("finalize_"):
                # Finalize tool — this is the termination signal
                try:
                    tool_fn = tool_map[tool_name]
                    finalize_output = await tool_fn.ainvoke(tool_args)
                    if isinstance(finalize_output, dict):
                        finalized_result = finalize_output
                    else:
                        finalized_result = json.loads(finalize_output) if isinstance(finalize_output, str) else {}
                except Exception as exc:
                    logger.warning("worker_finalize_error", tool=tool_name, error=str(exc))
                    finalized_result = {"error": str(exc)}

                tool_results.append(ToolMessage(
                    content=json.dumps({"status": "finalized", "artifact_type": artifact_type}),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                ))
                hit_finalize = True

            elif tool_name == "run_sql":
                # Worker SQL execution — cached in Redis
                try:
                    tool_fn = tool_map["run_sql"]
                    sql_result = await tool_fn.ainvoke(tool_args)
                    if isinstance(sql_result, str):
                        sql_result = json.loads(sql_result)
                except Exception as exc:
                    sql_result = {"error": str(exc), "query_id": None}

                # Track executed queries for state
                executed_queries.append({
                    "query_id": sql_result.get("query_id"),
                    "sql": tool_args.get("sql", ""),
                    "label": tool_args.get("label", ""),
                    "row_count": sql_result.get("row_count", 0),
                    "truncated": sql_result.get("truncated", False),
                    "error": sql_result.get("error"),
                })

                tool_results.append(ToolMessage(
                    content=json.dumps(sql_result),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                ))

                # Emit progress for each SQL run
                seq = await seq_counter.next()
                await ws_send(make_step(
                    chat_id=chat_id,
                    turn_id=turn_id,
                    seq=seq,
                    name=StepName.ARTIFACT_PROGRESS,
                    status="in_progress",
                    title=f"Executing SQL — Worker {worker_id}",
                    detail=tool_args.get("label", "Running query…"),
                    reasoning=f"Query returned {sql_result.get('row_count', '?')} rows",
                    worker_id=worker_id,
                ))

            else:
                # Other tools (get_table_details, get_column_unique_values, fetch_business_rule)
                try:
                    tool_fn = tool_map[tool_name]
                    result = await tool_fn.ainvoke(tool_args)
                    result_str = json.dumps(result) if not isinstance(result, str) else result
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)})

                tool_results.append(ToolMessage(
                    content=result_str,
                    tool_call_id=tool_call_id,
                    name=tool_name,
                ))

        messages.extend(tool_results)

        if hit_finalize:
            break  # Worker is done

    # ── Post-loop: promote artifact ───────────────────────────────────
    if not finalized_result:
        logger.warning("worker_no_finalize", worker_id=worker_id)
        return _error_result(worker_state, "Worker did not call a finalize tool within iteration limit.")

    if "error" in finalized_result:
        return _error_result(worker_state, finalized_result["error"])

    # Get the referenced query result from Redis
    query_id = finalized_result.get("query_id")
    query_result: dict = {}
    if query_id:
        query_result = await get_cached_query_result(
            turn_id=turn_id,
            worker_id=worker_id,
            query_id=query_id,
            redis=redis_service,
        ) or {}

    # Promote to Postgres
    try:
        artifact_id = await _promote_artifact(
            finalized=finalized_result,
            worker_state=worker_state,
            query_result=query_result,
            effective_db_id=effective_db_id,
            supabase_service=supabase_service,
            chat_service=chat_service,
        )
    except Exception as exc:
        logger.error("worker_promote_failed", worker_id=worker_id, error=str(exc))
        return _error_result(worker_state, f"Failed to save artifact: {exc}")

    # ── Emit: worker done ─────────────────────────────────────────────
    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=chat_id,
        turn_id=turn_id,
        seq=seq,
        name=StepName.ARTIFACT_PROGRESS,
        status="done",
        title=f"{artifact_type.upper()} Ready — {finalized_result.get('title', '')}",
        detail=finalized_result.get("note", ""),
        reasoning="",
        artifact_id=artifact_id,
        worker_id=worker_id,
    ))

    logger.info(
        "worker_complete",
        worker_id=worker_id,
        artifact_id=artifact_id,
        artifact_type=artifact_type,
    )

    return {
        "artifact_results": [{
            "artifact_id": artifact_id,
            "type": finalized_result.get("artifact_type", artifact_type),
            "title": finalized_result.get("title", "Untitled"),
            "note": finalized_result.get("note", ""),
            "key_numbers": finalized_result.get("key_numbers", {}),
            "status": "fresh",
            "error_message": None,
        }]
    }


def _error_result(worker_state: dict, error_message: str) -> dict:
    """Return a failed artifact result."""
    return {
        "artifact_results": [{
            "artifact_id": str(uuid.uuid4()),
            "type": worker_state.get("artifact_type", "table"),
            "title": f"Failed: {worker_state.get('task_description', '')[:60]}",
            "note": error_message,
            "key_numbers": {},
            "status": "error",
            "error_message": error_message,
        }]
    }
