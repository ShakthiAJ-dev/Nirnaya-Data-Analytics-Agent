"""
app/websocket/sql_chat_agent/orchestrator_graph.py
----------------------------------------------------
LangGraph StateGraph definition for the orchestrator.

Graph topology
──────────────
  START
    │
    ▼
  skim_tables            (pure context assembly, no LLM)
    │
    ▼
  discovery_loop  ◄──────────────────────────────┐
    │                                              │
    ├─ [tool calls?] ──► tool_executor ────────────┘
    │
    ├─ [no tool calls / signal_ready_to_decide]
    ▼
  decide_node            (forced structured output: direct | ask_user | dispatch)
    │
    ├─ [direct_response] ──► direct_response_node ──► END
    │
    ├─ [ask_user] ──► ask_user_node (interrupt) ──► [resume] ──► discovery_loop
    │
    └─ [dispatch_artifacts] ──► dispatch_artifacts_node
                                   │
                                   │  [Send × N parallel workers]
                                   ▼
                              run_worker_node × N   (parallel)
                                   │
                                   ▼  (all complete)
                              join_artifacts_node
                                   │
                                   ▼
                              synthesize_final_node ──► END

LangGraph concepts used
────────────────────────
  StateGraph           — typed state flowing through nodes
  add_messages reducer — appends LLM messages without duplicating
  operator.add reducer — accumulates artifact results from parallel workers
  ToolNode             — not used (custom tool executor for state-aware tools)
  Send                 — fans out to N run_worker_node instances in parallel
  interrupt()          — pauses graph at ask_user; resumes via Command(resume=answer)
  RunnableConfig       — carries non-serialisable objects (ws_send, services)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.core.logging import get_logger
from .events import StepName, make_ask_user, make_final, make_step
from .prompts import (
    DECIDE_SYSTEM,
    SYNTHESIZE_SYSTEM,
    build_orchestrator_system_prompt,
)
from .state import OrchestratorState
from .tools_orchestrator import create_orchestrator_tools
from .worker_graph import run_worker

logger = get_logger(__name__)

_MAX_DISCOVERY_ITERATIONS = 8
_MAX_ARTIFACTS = 6

# Default fallback model if FE doesn't specify one
_DEFAULT_MODEL = "claude-4.5-haiku"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_ws(config: RunnableConfig):
    """Extract ws_send + seq_counter + services from config."""
    cfg = config.get("configurable", {})
    return (
        cfg["ws_send"],
        cfg["seq_counter"],
        cfg["llm_service"],
        cfg["supabase_service"],
        cfg["redis_service"],
        cfg["chat_service"],
        cfg["full_metadata"],
    )


def _model(config: RunnableConfig) -> tuple[str, str | None]:
    """Return (model_name, provider) from config. Falls back to default."""
    cfg = config.get("configurable", {})
    return cfg.get("model", _DEFAULT_MODEL), cfg.get("provider")


# ---------------------------------------------------------------------------
# Node: skim_tables
# Pure context assembly — no LLM, just builds the discovery_messages seed.
# ---------------------------------------------------------------------------

async def skim_tables_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, supabase_service, _, _, full_metadata = await _get_ws(config)

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.LOADING_CONTEXT,
        status="in_progress",
        title="Loading Database Context",
        detail=f"Loading schema for {len(state['tables_overview'])} tables",
        reasoning="Building context window with schema, business rules, and conversation history",
    ))

    # Build the initial system + user message for the discovery LLM
    system_prompt = build_orchestrator_system_prompt(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        business_rules_index=state["business_rules_index"],
        recent_turns=state["recent_turns"],
    )

    seed_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["user_message"]),
    ]

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.LOADING_CONTEXT,
        status="done",
        title="Context Loaded",
        detail=f"Schema with {len(state['tables_overview'])} tables and {len(state['business_rules_index'])} business rules ready",
        reasoning="",
    ))

    return {
        "discovery_messages": seed_messages,
        "discovery_iterations": 0,
        "fetched_table_details": {},
        "discovery_results": [],
        "artifact_results": [],
    }


# ---------------------------------------------------------------------------
# Node: discovery_loop
# ReAct-style: LLM + tools, loops until ready to decide.
# ---------------------------------------------------------------------------

async def discovery_loop_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, supabase_service, _, _, full_metadata = await _get_ws(config)

    iteration = state.get("discovery_iterations", 0)

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.ANALYZING_QUESTION,
        status="in_progress",
        title="Analyzing Question" if iteration == 0 else "Continuing Discovery",
        detail=f"Exploring schema to understand what data is needed (iteration {iteration + 1})",
        reasoning="",
    ))

    # Build tools for this turn
    orchestrator_tools = create_orchestrator_tools(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        supabase_service=supabase_service,
    )

    try:
        model, provider = _model(config)
        response: AIMessage = await llm_service.ainvoke(
            state["discovery_messages"],
            model=model,
            tools=orchestrator_tools,
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
        )
    except Exception as exc:
        logger.error("discovery_loop_llm_error", error=str(exc))
        # Return error state — will route to direct_response with error message
        return {
            "discovery_messages": [AIMessage(content=f"Error during discovery: {exc}")],
            "discovery_iterations": iteration + 1,
        }

    return {
        "discovery_messages": [response],
        "discovery_iterations": iteration + 1,
    }


# ---------------------------------------------------------------------------
# Edge routing from discovery_loop
# ---------------------------------------------------------------------------

def route_after_discovery(state: OrchestratorState) -> Literal["tool_executor", "decide_node"]:
    """
    Route based on the last AI message:
    - Has tool_calls AND not all are signal_ready_to_decide → run tools
    - No tool_calls OR called signal_ready_to_decide → decide
    - Max iterations exceeded → force decide
    """
    iteration = state.get("discovery_iterations", 0)
    if iteration >= _MAX_DISCOVERY_ITERATIONS:
        logger.warning("discovery_max_iterations_reached", iteration=iteration)
        return "decide_node"

    messages = state.get("discovery_messages", [])
    if not messages:
        return "decide_node"

    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", []) or []
    if not tool_calls:
        return "decide_node"

    # If ONLY tool call is signal_ready_to_decide → go to decide
    non_ready = [tc for tc in tool_calls if tc["name"] != "signal_ready_to_decide"]
    if not non_ready:
        return "decide_node"

    return "tool_executor"


# ---------------------------------------------------------------------------
# Node: tool_executor (custom — handles state-aware tools)
# ---------------------------------------------------------------------------

async def tool_executor_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, supabase_service, redis_service, _, full_metadata = await _get_ws(config)

    orchestrator_tools = create_orchestrator_tools(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        supabase_service=supabase_service,
    )
    tool_map = {t.name: t for t in orchestrator_tools}

    messages = state["discovery_messages"]
    last_ai = messages[-1]
    tool_calls = getattr(last_ai, "tool_calls", []) or []

    tool_messages: list[ToolMessage] = []
    new_discovery_results: list[dict] = []

    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        if tool_name == "signal_ready_to_decide":
            # Just echo it — routing already handles this
            tool_messages.append(ToolMessage(
                content=json.dumps({"status": "ready"}),
                tool_call_id=tool_call_id,
                name=tool_name,
            ))
            continue

        seq = await seq_counter.next()
        await ws_send(make_step(
            chat_id=state["chat_id"],
            turn_id=state["turn_id"],
            seq=seq,
            name=StepName.RUNNING_DISCOVERY,
            status="in_progress",
            title=f"Running Tool: {tool_name.replace('_', ' ').title()}",
            detail=str(tool_args)[:200],
            reasoning="",
        ))

        try:
            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})
            else:
                result = await tool_fn.ainvoke(tool_args)
                if isinstance(result, list):
                    # run_discovery_queries returns a list
                    new_discovery_results.extend(result)
                result_str = json.dumps(result) if not isinstance(result, str) else result
        except Exception as exc:
            result_str = json.dumps({"error": str(exc)})

        tool_messages.append(ToolMessage(
            content=result_str,
            tool_call_id=tool_call_id,
            name=tool_name,
        ))

    updates: dict[str, Any] = {"discovery_messages": tool_messages}
    if new_discovery_results:
        updates["discovery_results"] = state.get("discovery_results", []) + new_discovery_results

    return updates


# ---------------------------------------------------------------------------
# Node: decide_node — forced structured output
# ---------------------------------------------------------------------------

async def decide_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.DECIDING,
        status="in_progress",
        title="Making Decision",
        detail="Determining how to best answer this question",
        reasoning="",
    ))

    # Build decision prompt
    discovery_summary = _summarise_discovery(state)

    decide_messages = [
        SystemMessage(content=DECIDE_SYSTEM),
        HumanMessage(content=(
            f"User question: {state['user_message']}\n\n"
            f"Discovery findings:\n{discovery_summary}\n\n"
            "Choose one action and return it as JSON:\n\n"
            "Option A — Direct response (no data needed):\n"
            '{"action": "direct_response", "markdown": "...your full answer here..."}\n\n'
            "Option B — Ask user for clarification:\n"
            '{"action": "ask_user", "question": "...", "mode": "mcq"|"free_text", "options": [...] or null}\n\n'
            "Option C — Dispatch artifact workers:\n"
            '{"action": "dispatch_artifacts", "artifacts": [{"artifact_type": "kpi"|"chart"|"table", '
            '"task_description": "...", "tables_in_scope": [...], "suggested_chart_type": null|"line"|..., '
            '"metric_clarification": "shared definitions all artifacts must follow", '
            '"relevant_business_rule_ids": [...]}]}'
        )),
    ]

    try:
        model, provider = _model(config)
        response: AIMessage = await llm_service.ainvoke(
            decide_messages,
            model=model,
            max_tokens=2048,
            temperature=0.1,
            provider=provider,
        )
        content = response.content if isinstance(response.content, str) else ""
        # Strip markdown code fences if model wraps in ```json
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        decide_output = json.loads(content)
    except Exception as exc:
        logger.warning("decide_node_parse_error", error=str(exc))
        # Fall back to direct response with error
        decide_output = {
            "action": "direct_response",
            "markdown": "I had trouble deciding how to answer that. Could you rephrase your question?",
        }

    return {"decide_output": decide_output}


def _summarise_discovery(state: OrchestratorState) -> str:
    """Build a compact summary of discovery results for the decide prompt."""
    parts: list[str] = []

    # Discovery query results
    dr = state.get("discovery_results", [])
    if dr:
        parts.append(f"Discovery queries run: {len(dr)}")
        for r in dr[:3]:  # show first 3
            parts.append(f"  - {r.get('label', '')}: {r.get('row_count', '?')} rows")
            prows = r.get("preview_rows", [])
            if prows:
                parts.append(f"    Sample: {json.dumps(prows[:2])}")

    # Tables viewed
    ft = state.get("fetched_table_details", {})
    if ft:
        parts.append(f"Tables examined: {', '.join(ft.keys())}")

    if not parts:
        parts.append("No discovery queries run yet — answering from schema context alone.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Edge routing from decide_node
# ---------------------------------------------------------------------------

def route_after_decide(state: OrchestratorState) -> Literal[
    "direct_response_node", "ask_user_node", "dispatch_artifacts_node"
]:
    action = (state.get("decide_output") or {}).get("action", "direct_response")
    if action == "ask_user":
        return "ask_user_node"
    if action == "dispatch_artifacts":
        return "dispatch_artifacts_node"
    return "direct_response_node"


# ---------------------------------------------------------------------------
# Node: direct_response_node
# ---------------------------------------------------------------------------

async def direct_response_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)

    decide_output = state.get("decide_output") or {}
    markdown = decide_output.get("markdown", "I wasn't able to generate a response.")

    # Generate follow-up questions
    follow_ups = await _generate_follow_ups(
        user_message=state["user_message"],
        markdown=markdown,
        llm_service=llm_service,
        model=model,
        provider=provider,
    )

    seq = await seq_counter.next()
    await ws_send(make_final(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        markdown=markdown,
        artifact_ids=[],
        follow_up_questions=follow_ups,
    ))

    return {
        "final_markdown": markdown,
        "follow_up_questions": follow_ups,
    }


# ---------------------------------------------------------------------------
# Node: ask_user_node — interrupt() / resume
# ---------------------------------------------------------------------------

async def ask_user_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, *_ = await _get_ws(config)

    decide_output = state.get("decide_output") or {}
    question = decide_output.get("question", "Could you clarify your question?")
    mode = decide_output.get("mode", "free_text")
    options = decide_output.get("options")

    seq = await seq_counter.next()
    await ws_send(make_ask_user(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        question=question,
        mode=mode,
        options=options,
    ))

    # ── INTERRUPT: graph pauses here, state is checkpointed ──────────
    # When the user answers (ask_user_response WS frame), entrypoint.py
    # calls graph.ainvoke(Command(resume=answer), config).
    # Execution continues from the line below.
    user_answer: str = interrupt({"question": question, "mode": mode, "options": options})

    if not user_answer or user_answer.strip() == "__skip__":
        user_answer = "User did not directly answer — proceed using best judgment and state assumptions made."

    logger.info("ask_user_resumed", chat_id=state["chat_id"])

    # Inject the answer back into discovery messages and loop
    return {
        "pending_question": None,
        "discovery_messages": [
            HumanMessage(content=f"Clarification from user: {user_answer}")
        ],
    }


# ---------------------------------------------------------------------------
# Node: dispatch_artifacts_node — fan-out via Send
# ---------------------------------------------------------------------------

def dispatch_artifacts_node(state: OrchestratorState) -> list[Send]:
    """
    Fan out to N parallel worker nodes via Send.
    Each Send carries a complete WorkerState payload.
    """
    decide_output = state.get("decide_output") or {}
    artifacts = decide_output.get("artifacts", [])[:_MAX_ARTIFACTS]

    sends: list[Send] = []
    for i, spec in enumerate(artifacts):
        tables_in_scope = spec.get("tables_in_scope", [])
        relevant_rule_ids = spec.get("relevant_business_rule_ids", [])
        full_metadata = {}  # will be pulled from config in worker

        # Pre-fetch table context from orchestrator's already-fetched details
        prefetched = {
            t: state.get("fetched_table_details", {}).get(t, state["full_metadata"].get("tables", {}).get(t, {}))
            for t in tables_in_scope
        }

        # Relevant business rules (full content)
        all_rules = state["full_metadata"].get("business_rules", [])
        relevant_rules = [
            r for r in all_rules
            if r.get("_id") in relevant_rule_ids or r.get("id") in relevant_rule_ids
        ]

        worker_payload = {
            "turn_id": state["turn_id"],
            "worker_id": str(i),
            "artifact_type": spec.get("artifact_type", "table"),
            "chat_id": state["chat_id"],
            "database_id": state["database_id"],
            "schema_name": state["schema_name"],
            "task_description": spec.get("task_description", ""),
            "metric_clarification": spec.get("metric_clarification", ""),
            "suggested_chart_type": spec.get("suggested_chart_type"),
            "tables_in_scope": tables_in_scope,
            "relevant_business_rule_ids": relevant_rule_ids,
            "prefetched_context": prefetched,
            "relevant_business_rules": relevant_rules,
            "worker_messages": [],
            "worker_iterations": 0,
            "executed_queries": [],
            "finalized": None,
        }
        sends.append(Send("run_worker_node", worker_payload))

    # Store dispatch plan in state (for reference by synthesize_final)
    return sends


# ---------------------------------------------------------------------------
# Node: run_worker_node — called by each Send
# ---------------------------------------------------------------------------

async def run_worker_node(worker_payload: dict, config: RunnableConfig) -> dict:
    """
    Entry point for each parallel worker. Receives WorkerState via Send.
    Returns {"artifact_results": [ArtifactResult]} for the operator.add reducer.
    """
    return await run_worker(worker_payload, config)


# ---------------------------------------------------------------------------
# Node: join_artifacts_node
# ---------------------------------------------------------------------------

async def join_artifacts_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, *_ = await _get_ws(config)

    results = state.get("artifact_results", [])
    fresh = sum(1 for r in results if r.get("status") == "fresh")
    errors = sum(1 for r in results if r.get("status") == "error")

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.JOINING_RESULTS,
        status="done",
        title="All Artifacts Ready",
        detail=f"{fresh} artifact(s) built successfully" + (f", {errors} failed" if errors else ""),
        reasoning="",
    ))

    return {}  # state already has artifact_results from workers


# ---------------------------------------------------------------------------
# Node: synthesize_final_node — forced structured output
# ---------------------------------------------------------------------------

async def synthesize_final_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.SYNTHESIZING,
        status="in_progress",
        title="Writing Analysis",
        detail="Synthesizing insights from all artifacts",
        reasoning="",
    ))

    results = state.get("artifact_results", [])
    results_summary = json.dumps([
        {
            "title": r["title"],
            "type": r["type"],
            "note": r["note"],
            "key_numbers": r["key_numbers"],
            "status": r["status"],
            "error_message": r.get("error_message"),
        }
        for r in results
    ], indent=2)

    synth_messages = [
        SystemMessage(content=SYNTHESIZE_SYSTEM),
        HumanMessage(content=(
            f"User's original question: {state['user_message']}\n\n"
            f"Artifact results:\n{results_summary}\n\n"
            'Return JSON: {"markdown": "...", "follow_up_questions": ["...", "...", "..."]}'
        )),
    ]

    markdown = ""
    follow_ups: list[str] = []

    try:
        model, provider = _model(config)
        response: AIMessage = await llm_service.ainvoke(
            synth_messages,
            model=model,
            max_tokens=2048,
            temperature=0.3,
            provider=provider,
        )
        content = response.content if isinstance(response.content, str) else ""
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(content)
        markdown = parsed.get("markdown", "")
        follow_ups = parsed.get("follow_up_questions", [])[:3]
    except Exception as exc:
        logger.warning("synthesize_parse_error", error=str(exc))
        # Fallback markdown
        fresh_results = [r for r in results if r["status"] == "fresh"]
        lines = ["Here is your analysis:"]
        for r in fresh_results:
            lines.append(f"\n**{r['title']}**: {r['note']}")
        markdown = "\n".join(lines)
        follow_ups = []

    artifact_ids = [r["artifact_id"] for r in results if r["status"] == "fresh"]

    seq = await seq_counter.next()
    await ws_send(make_final(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        markdown=markdown,
        artifact_ids=artifact_ids,
        follow_up_questions=follow_ups,
    ))

    return {
        "final_markdown": markdown,
        "follow_up_questions": follow_ups,
    }


# ---------------------------------------------------------------------------
# Helper: generate follow-up questions for direct responses
# ---------------------------------------------------------------------------

async def _generate_follow_ups(user_message: str, markdown: str, llm_service: Any, model: str, provider: str | None = None) -> list[str]:
    try:
        response: AIMessage = await llm_service.ainvoke(
            [
                SystemMessage(content="Generate exactly 2 follow-up questions that naturally extend this analysis. Return only a JSON array of strings: [\"...\", \"...\"]"),
                HumanMessage(content=f"Question: {user_message}\nAnswer: {markdown[:500]}"),
            ],
            model=model,
            max_tokens=512,
            temperature=0.5,
            provider=provider,
        )
        content = response.content if isinstance(response.content, str) else "[]"
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(content)[:3]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def build_orchestrator_graph(checkpointer: Any = None):
    """
    Compile and return the orchestrator StateGraph.

    Args:
        checkpointer: AsyncPostgresSaver instance (or None for no persistence).
                      Pass from CheckpointerService.checkpointer.

    Returns:
        CompiledStateGraph ready for .ainvoke()
    """
    graph = StateGraph(OrchestratorState)

    # ── Add nodes ─────────────────────────────────────────────────────
    graph.add_node("skim_tables", skim_tables_node)
    graph.add_node("discovery_loop", discovery_loop_node)
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("decide_node", decide_node)
    graph.add_node("direct_response_node", direct_response_node)
    graph.add_node("ask_user_node", ask_user_node)
    # dispatch_artifacts_node returns a list of Send objects — LangGraph
    # automatically fans out when a node returns [Send(...), Send(...)]
    graph.add_node("dispatch_artifacts_node", dispatch_artifacts_node)
    graph.add_node("run_worker_node", run_worker_node)
    graph.add_node("join_artifacts_node", join_artifacts_node)
    graph.add_node("synthesize_final_node", synthesize_final_node)

    # ── Edges ─────────────────────────────────────────────────────────
    graph.add_edge(START, "skim_tables")
    graph.add_edge("skim_tables", "discovery_loop")

    graph.add_conditional_edges(
        "discovery_loop",
        route_after_discovery,
        {"tool_executor": "tool_executor", "decide_node": "decide_node"},
    )
    graph.add_edge("tool_executor", "discovery_loop")

    graph.add_conditional_edges(
        "decide_node",
        route_after_decide,
        {
            "direct_response_node": "direct_response_node",
            "ask_user_node": "ask_user_node",
            "dispatch_artifacts_node": "dispatch_artifacts_node",
        },
    )

    # direct_response → END
    graph.add_edge("direct_response_node", END)

    # ask_user_node pauses via interrupt(); on resume → back to discovery_loop
    graph.add_edge("ask_user_node", "discovery_loop")

    # dispatch_artifacts_node returns [Send("run_worker_node", ...)]
    # LangGraph fans out automatically; all workers → join_artifacts_node
    graph.add_edge("run_worker_node", "join_artifacts_node")
    graph.add_edge("join_artifacts_node", "synthesize_final_node")
    graph.add_edge("synthesize_final_node", END)

    return graph.compile(checkpointer=checkpointer)

