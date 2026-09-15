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
import re
import uuid
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.core.logging import get_logger
from .events import StepName, make_ask_user, make_final, make_step
from .prompts import (
    DECIDE_SCHEMA,
    DECIDE_SYSTEM,
    SYNTHESIZE_SYSTEM,
    build_orchestrator_system_prompt,
    _format_recent_turns,
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


def _elapsed_ms(config: RunnableConfig) -> int:
    """Return milliseconds elapsed since the turn start (monotonic clock)."""
    import time
    cfg = config.get("configurable", {})
    start = cfg.get("turn_start_ms", 0)
    return int(time.monotonic() * 1000) - start if start else 0


def _model(config: RunnableConfig) -> tuple[str, str | None]:
    """Return (model_name, provider) from config. Falls back to default."""
    cfg = config.get("configurable", {})
    return cfg.get("model", _DEFAULT_MODEL), cfg.get("provider")


_PREAMBLE_TITLE_RE = re.compile(r"TITLE:\s*(.+?)(?:\n|$)", re.IGNORECASE)
_PREAMBLE_REASON_RE = re.compile(r"REASON:\s*([\s\S]+?)(?=TITLE:|$)", re.IGNORECASE)


def _parse_preamble(preamble: str, fallback_title: str = "") -> tuple[str, str]:
    """
    Parse structured TITLE/REASON block from LLM preamble.
    Returns (title, reasoning). Falls back gracefully when block is absent
    (e.g. model ignored the instruction) — title = first line, reasoning = full text.
    """
    if not preamble:
        return fallback_title, ""
    title_m = _PREAMBLE_TITLE_RE.search(preamble)
    reason_m = _PREAMBLE_REASON_RE.search(preamble)
    if title_m:
        title = title_m.group(1).strip()
        reasoning = reason_m.group(1).strip() if reason_m else preamble.strip()
        return title or fallback_title, reasoning
    # No structured block — use first line as title, full text as reasoning
    lines = preamble.strip().splitlines()
    title = lines[0].strip()[:100] if lines else fallback_title
    return title or fallback_title, preamble.strip()


def _extract_reasoning(response: AIMessage) -> str:
    """
    Extract the model's actual reasoning/thinking text from an AIMessage.
    Returns the FULL text — no truncation. Handles:
    - Anthropic extended_thinking: content blocks with type="thinking"
    - Bedrock / other providers: response_metadata.get("thinking")
    - Additional kwargs (some providers)
    - Plain text fallback when there are no tool calls
    Returns an empty string if none found (never crashes).
    """
    try:
        # 1. Anthropic extended_thinking — content is a list of blocks
        if isinstance(response.content, list):
            thinking_parts: list[str] = []
            for block in response.content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking:
                        thinking_parts.append(str(thinking))
            if thinking_parts:
                return "\n\n".join(thinking_parts)

        # 2. Bedrock / response_metadata thinking field
        metadata = getattr(response, "response_metadata", {}) or {}
        thinking = metadata.get("thinking") or metadata.get("reasoning")
        if thinking:
            return str(thinking)

        # 3. Additional kwargs (some providers surface it here)
        additional = getattr(response, "additional_kwargs", {}) or {}
        thinking = additional.get("thinking") or additional.get("reasoning")
        if thinking:
            return str(thinking)

        # 4. Plain text fallback — only when no tool calls (avoid dumping JSON tool schema)
        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls and isinstance(response.content, str) and response.content.strip():
            return response.content.strip()

    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Node: skim_tables
# Pure context assembly — no LLM, just builds the discovery_messages seed.
# ---------------------------------------------------------------------------

async def skim_tables_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, _, _, _, _, full_metadata = await _get_ws(config)

    # Log the full prior conversation turns exactly as they will be formatted into the system prompt
    recent_turns = state.get("recent_turns", [])
    logger.info(
        "chat_messages_context",
        turn_id=state["turn_id"],
        recent_turn_count=len(recent_turns),
        recent_turns=recent_turns,
    )

    tables = full_metadata.get("tables", {})
    table_names = list(tables.keys())
    n_tables = len(table_names)
    n_rules = len(state.get("business_rules_index", []))

    table_list = ", ".join(table_names) if table_names else "none"
    reasoning = f"Tables: {table_list}"
    if n_rules:
        reasoning += f" · {n_rules} business rule{'s' if n_rules != 1 else ''}"
    if recent_turns:
        reasoning += f" · {len(recent_turns)} prior turn{'s' if len(recent_turns) != 1 else ''} in context"

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.LOADING_CONTEXT,
        status="done",
        title="Getting the project details ready",
        detail=f"{n_tables} table{'s' if n_tables != 1 else ''} loaded",
        reasoning=reasoning,
    ))

    # ask_user_count persists across turns — read without resetting
    ask_user_count = state.get("ask_user_count", 0)

    # Build the initial system + user message for the discovery LLM
    system_prompt = build_orchestrator_system_prompt(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        business_rules_index=state["business_rules_index"],
        recent_turns=recent_turns,
        ask_user_count=ask_user_count,
    )

    seed_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["user_message"]),
    ]

    return {
        "discovery_messages": seed_messages,
        "discovery_iterations": 0,
        "fetched_table_details": {},
        "discovery_results": [],
        "artifact_results": [],
        "discovery_key_findings": "",   # reset each turn
    }


# ---------------------------------------------------------------------------
# Node: discovery_loop
# ReAct-style: LLM + tools, loops until ready to decide.
# ---------------------------------------------------------------------------



def _preamble_text(response: AIMessage) -> str:
    """
    Extract the LLM's plain text preamble that appears *before* any tool calls.
    Returns empty string if the response is pure text (no tool calls) or has no
    text content alongside its tool calls.
    """
    tool_calls = getattr(response, "tool_calls", []) or []
    if not tool_calls:
        return ""  # pure text — handled by shortcut_decide_node path, not here
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts).strip()
    return ""


async def discovery_loop_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, supabase_service, _, _, full_metadata = await _get_ws(config)

    iteration = state.get("discovery_iterations", 0)

    logger.info(
        "discovery_loop_start",
        turn_id=state["turn_id"],
        iteration=iteration,
        message_count=len(state.get("discovery_messages", [])),
        user_message=state["user_message"][:120],
    )

    # Build tools for this turn
    has_business_rules = bool(state.get("business_rules_index", []))
    orchestrator_tools = create_orchestrator_tools(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        supabase_service=supabase_service,
        has_business_rules=has_business_rules,
        ask_user_count=state.get("ask_user_count", 0),
    )

    try:
        model, provider = _model(config)
        # Log the full conversation history being passed to this LLM call
        logger.info(
            "discovery_loop_llm_call",
            turn_id=state["turn_id"],
            iteration=iteration,
            model=model,
            provider=provider,
            tools=[t.name for t in orchestrator_tools],
            message_count=len(state["discovery_messages"]),
            chat_history=[
                {
                    "role": type(m).__name__,
                    "content_preview": (
                        m.content if isinstance(m.content, str)
                        else str(m.content)
                    )[:500],
                }
                for m in state["discovery_messages"]
            ],
        )
        response: AIMessage = await llm_service.ainvoke(
            state["discovery_messages"],
            model=model,
            tools=orchestrator_tools,
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
        )
    except Exception as exc:
        logger.error("discovery_loop_llm_error", turn_id=state["turn_id"], error=str(exc))
        return {
            "discovery_messages": [AIMessage(content=f"Error during discovery: {exc}")],
            "discovery_iterations": iteration + 1,
        }

    tool_calls = getattr(response, "tool_calls", []) or []
    logger.info(
        "discovery_loop_llm_response",
        turn_id=state["turn_id"],
        iteration=iteration,
        has_tool_calls=bool(tool_calls),
        tool_names=[tc["name"] for tc in tool_calls],
        content_preview=(response.content if isinstance(response.content, str) else str(response.content))[:200],
    )

    # Extract reasoning / thinking blocks (full, untruncated)
    reasoning_text = _extract_reasoning(response)

    # Extract LLM preamble (text before tool calls) — this is the model's own reasoning
    preamble = _preamble_text(response)

    # Parse structured TITLE/REASON from preamble; fall back to thinking blocks
    _fallback_title = "Got the Lay of the Land" if iteration == 0 else "Dug a Little Deeper"
    display_title, display_reasoning = _parse_preamble(preamble, _fallback_title)
    if not display_reasoning:
        display_reasoning = reasoning_text  # use thinking blocks if preamble absent

    # Emit a "done" step with LLM-generated title + reasoning
    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.ANALYZING_QUESTION,
        status="done",
        title=display_title,
        detail="Ready to look at the data" if iteration == 0 else "Gathered more context",
        reasoning=display_reasoning,
    ))

    return {
        "discovery_messages": [response],
        "discovery_iterations": iteration + 1,
    }


# ---------------------------------------------------------------------------
# Edge routing from discovery_loop
# ---------------------------------------------------------------------------

def route_after_discovery(state: OrchestratorState) -> Literal["tool_executor", "shortcut_decide_node", "decide_node", "ask_user_node"]:
    """
    Route based on the last AI message:
    - ask_user_during_discovery tool call → ask_user_node (bypasses tool_executor)
    - Has other tool_calls → tool_executor
    - No tool_calls + very short first-iteration response → shortcut_decide_node (likely greeting)
    - Everything else → decide_node
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

    # ask_user_during_discovery takes priority — route directly to ask_user_node
    if any(tc["name"] == "ask_user_during_discovery" for tc in tool_calls):
        logger.info("discovery_routing", decision="ask_user_node", reason="ask_user_during_discovery", iteration=iteration)
        return "ask_user_node"

    if not tool_calls:
        content = last.content if isinstance(last.content, str) else ""
        if not content and isinstance(last.content, list):
            content = " ".join(
                b.get("text", "") for b in last.content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        if content and len(content.strip()) > 20:
            # Only shortcut for very short first-iteration responses (likely greetings).
            # Longer responses and all later iterations go through decide_node so the
            # decider can choose to dispatch visual artifacts instead of a plain text answer.
            if iteration == 1 and len(content.strip()) < 200:
                logger.info("discovery_routing", decision="shortcut_decide_node", reason="short_first_response", iteration=iteration)
                return "shortcut_decide_node"
            logger.info("discovery_routing", decision="decide_node", reason="text_answer_to_decider", iteration=iteration)
            return "decide_node"
        logger.info("discovery_routing", decision="decide_node", reason="no_tool_calls_empty_content", iteration=iteration)
        return "decide_node"

    # If ONLY tool call is signal_ready_to_decide → go to decide
    non_ready = [tc for tc in tool_calls if tc["name"] not in ("signal_ready_to_decide", "ask_user_during_discovery")]
    if not non_ready:
        logger.info("discovery_routing", decision="decide_node", reason="signal_ready_to_decide", iteration=iteration)
        return "decide_node"

    logger.info("discovery_routing", decision="tool_executor", tools=[tc["name"] for tc in non_ready], iteration=iteration)
    return "tool_executor"


# ---------------------------------------------------------------------------
# Node: tool_executor (custom — handles state-aware tools)
# ---------------------------------------------------------------------------

async def tool_executor_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    _, _, _, supabase_service, _, _, full_metadata = await _get_ws(config)

    orchestrator_tools = create_orchestrator_tools(
        schema_name=state["schema_name"],
        full_metadata=full_metadata,
        supabase_service=supabase_service,
    )
    tool_map = {t.name: t for t in orchestrator_tools}

    messages = state["discovery_messages"]
    last_ai = messages[-1]
    tool_calls = getattr(last_ai, "tool_calls", []) or []

    # Log preamble title from the AI message that triggered these tool calls
    raw_preamble = _preamble_text(last_ai)
    _preamble_title, _ = _parse_preamble(raw_preamble)

    logger.info(
        "tool_executor_start",
        turn_id=state["turn_id"],
        tool_count=len(tool_calls),
        tools=[{"name": tc["name"], "args": tc["args"]} for tc in tool_calls],
        preamble_title=_preamble_title,
    )

    tool_messages: list[ToolMessage] = []
    new_discovery_results: list[dict] = []
    new_fetched_details: dict = {}  # populated when get_table_details is called
    new_key_findings: str = ""  # populated when signal_ready_to_decide is called
    new_ask_user_decide_output: dict = {}  # populated when ask_user_during_discovery is called

    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        if tool_name == "signal_ready_to_decide":
            # Just echo it — routing already handles this
            # Extract the key-findings reason paragraph and store in state
            reason = tool_args.get("reason", "")
            if reason:
                new_key_findings = reason
            tool_messages.append(ToolMessage(
                content=json.dumps({"status": "ready"}),
                tool_call_id=tool_call_id,
                name=tool_name,
            ))
            continue

        if tool_name == "ask_user_during_discovery":
            # Store the question details in decide_output so ask_user_node can read them.
            # route_after_discovery routes directly to ask_user_node so this tool message
            # is added but execution jumps out of tool_executor.
            new_ask_user_decide_output = {
                "action": "ask_user",
                "question": tool_args.get("question", "Could you clarify your question?"),
                "mode": tool_args.get("mode", "free_text"),
                "options": tool_args.get("options"),
            }
            tool_messages.append(ToolMessage(
                content=json.dumps({"status": "ask_user_triggered"}),
                tool_call_id=tool_call_id,
                name=tool_name,
            ))
            continue

        logger.info(
            "tool_call",
            turn_id=state["turn_id"],
            tool=tool_name,
            args=tool_args,
        )

        # Use LLM-parsed title from preamble if available; fall back to tool display name
        try:
            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})
            else:
                result = await tool_fn.ainvoke(tool_args)
                if isinstance(result, list):
                    # run_discovery_queries returns a list
                    new_discovery_results.extend(result)
                elif tool_name == "get_table_details" and isinstance(result, dict):
                    # Cache fetched details so workers can reuse without re-fetching
                    new_fetched_details.update(
                        {k: v for k, v in result.items() if "error" not in v}
                    )
                result_str = json.dumps(result) if not isinstance(result, str) else result
            logger.info(
                "tool_result",
                turn_id=state["turn_id"],
                tool=tool_name,
                result_preview=result_str[:300],
            )
        except Exception as exc:
            result_str = json.dumps({"error": str(exc)})
            logger.warning(
                "tool_error",
                turn_id=state["turn_id"],
                tool=tool_name,
                error=str(exc),
            )

        tool_messages.append(ToolMessage(
            content=result_str,
            tool_call_id=tool_call_id,
            name=tool_name,
        ))

    updates: dict[str, Any] = {"discovery_messages": tool_messages}
    if new_discovery_results:
        updates["discovery_results"] = state.get("discovery_results", []) + new_discovery_results
    if new_fetched_details:
        updates["fetched_table_details"] = {**state.get("fetched_table_details", {}), **new_fetched_details}
    if new_key_findings:
        updates["discovery_key_findings"] = new_key_findings
    if new_ask_user_decide_output:
        updates["decide_output"] = new_ask_user_decide_output

    logger.info(
        "tool_executor_done",
        turn_id=state["turn_id"],
        tools_executed=len(tool_messages),
        new_query_results=len(new_discovery_results),
    )
    return updates


# ---------------------------------------------------------------------------
# Node: decide_node — forced structured output
# ---------------------------------------------------------------------------

async def shortcut_decide_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    """
    Fast path: the discovery LLM already produced a complete text answer with no
    tool calls. Wrap it in a decide_output dict and skip the decide_node LLM call
    entirely — saving one full LLM round trip.
    """
    ws_send, seq_counter, *_ = await _get_ws(config)

    messages = state.get("discovery_messages", [])
    last = messages[-1] if messages else None
    content = ""
    if last is not None:
        raw = last.content
        if isinstance(raw, str):
            content = raw.strip()
        elif isinstance(raw, list):
            content = " ".join(
                b.get("text", "") for b in raw
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()

    decide_output = {"action": "direct_response", "markdown": content}

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.DECIDING,
        status="done",
        title="Crafting Your Answer",
        detail="Using the findings to write a clear response",
        reasoning="",
    ))

    logger.info("shortcut_decide", turn_id=state["turn_id"], markdown_len=len(content))
    return {"decide_output": decide_output}


async def decide_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)

    # Build decision prompt
    discovery_summary = _summarise_discovery(state)

    decide_messages = [
        SystemMessage(content=DECIDE_SYSTEM),
        HumanMessage(content=(
            f"User question: {state['user_message']}\n\n"
            f"Discovery findings:\n{discovery_summary}\n\n"
            "Choose one action and return it as JSON. Always include step_title and reasoning.\n\n"
            f"Option A — Direct response (no data needed):\n{DECIDE_SCHEMA['direct_response']}\n\n"
            f"Option B — Ask user for clarification:\n{DECIDE_SCHEMA['ask_user']}\n\n"
            f"Option C — Dispatch artifact workers:\n{DECIDE_SCHEMA['dispatch_artifacts']}"
        )),
    ]

    # Log messages being passed so we can trace what the LLM sees
    logger.info(
        "decide_node_messages",
        turn_id=state["turn_id"],
        message_count=len(decide_messages),
        messages_preview=[
            {"role": type(m).__name__, "content_preview": (m.content if isinstance(m.content, str) else str(m.content))[:300]}
            for m in decide_messages
        ],
    )

    decide_output: dict = {}
    reasoning_text = ""
    step_title = ""
    try:
        model, provider = _model(config)
        logger.info(
            "decide_node_llm_call",
            turn_id=state["turn_id"],
            model=model,
            discovery_queries=len(state.get("discovery_results", [])),
            tables_examined=list(state.get("fetched_table_details", {}).keys()),
        )
        response: AIMessage = await llm_service.ainvoke(
            decide_messages,
            model=model,
            max_tokens=2048,
            temperature=0.1,
            provider=provider,
        )
        reasoning_text = _extract_reasoning(response)  # thinking blocks if present
        content = response.content if isinstance(response.content, str) else ""
        # Strip markdown code fences if model wraps in ```json
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        decide_output = json.loads(content)
        # Pull LLM-generated title + reasoning out of the JSON output
        step_title = decide_output.pop("step_title", "")  # remove from output dict
        llm_reasoning = decide_output.pop("reasoning", "")
        # Prefer explicit LLM reasoning over thinking blocks
        if llm_reasoning:
            reasoning_text = llm_reasoning
        logger.info(
            "decide_node_output",
            turn_id=state["turn_id"],
            action=decide_output.get("action"),
            step_title=step_title,
            artifact_count=len(decide_output.get("artifacts", [])),
            artifact_types=[a.get("artifact_type") for a in decide_output.get("artifacts", [])],
            artifact_tasks=[a.get("task_description", "")[:80] for a in decide_output.get("artifacts", [])],
            question=decide_output.get("question", ""),
            reasoning=reasoning_text,
        )
    except Exception as exc:
        logger.warning("decide_node_parse_error", turn_id=state["turn_id"], error=str(exc))
        # Fall back to direct response with error
        decide_output = {
            "action": "direct_response",
            "markdown": "I had trouble deciding how to answer that. Could you rephrase your question?",
        }

    # Emit done step — use LLM-generated title when available, fall back to action-derived title
    seq = await seq_counter.next()
    action = decide_output.get("action", "direct_response")
    _action_titles = {
        "direct_response":    "Crafting Your Answer",
        "dispatch_artifacts": "Planning the Analysis",
        "ask_user":           "Need a Quick Clarification",
    }
    _action_details = {
        "direct_response":    "Writing a clear, direct response",
        "dispatch_artifacts": f"Preparing {len(decide_output.get('artifacts', []))} visual{'s' if len(decide_output.get('artifacts', [])) != 1 else ''} for you",
        "ask_user":           decide_output.get("question", ""),
    }
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.DECIDING,
        status="done",
        title=step_title or _action_titles.get(action, "Crafting Your Answer"),
        detail=_action_details.get(action, ""),
        reasoning=reasoning_text,  # full, untruncated
    ))

    return {"decide_output": decide_output}


def _summarise_discovery(state: OrchestratorState) -> str:
    """Build a rich summary of discovery results for the decide prompt."""
    parts: list[str] = []

    # Discovery query results (all of them, not just first 3)
    dr = state.get("discovery_results", [])
    if dr:
        parts.append(f"Discovery queries run: {len(dr)}")
        for r in dr:  # show ALL queries
            parts.append(f"  - {r.get('label', '')}: {r.get('row_count', '?')} rows")
            prows = r.get("preview_rows", [])
            if prows:
                parts.append(f"    Sample: {json.dumps(prows[:2])}")

    # Tables viewed with column count
    ft = state.get("fetched_table_details", {})
    if ft:
        table_details = []
        for tname, tinfo in ft.items():
            ncols = len(tinfo.get("columns", []))
            table_details.append(f"{tname} ({ncols} columns)")
        parts.append(f"Tables examined: {', '.join(table_details)}")

    # Business rules fetched during discovery (extracted from ToolMessages)
    fetched_rules = _extract_fetched_business_rules(state)
    if fetched_rules:
        parts.append(f"Business rules fetched: {', '.join(fetched_rules)}")

    # Key-findings paragraph from signal_ready_to_decide
    key_findings = state.get("discovery_key_findings", "")
    if key_findings:
        parts.append(f"\nKey findings from discovery:\n{key_findings}")

    if not parts:
        parts.append("No discovery queries run yet — answering from schema context alone.")

    return "\n".join(parts)


def _extract_fetched_business_rules(state: OrchestratorState) -> list[str]:
    """Return list of 'rule_id: title' strings fetched via fetch_business_rule during discovery."""
    fetched: list[str] = []
    for msg in state.get("discovery_messages", []):
        if getattr(msg, "name", "") == "fetch_business_rule":
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else {}
                for rule_id, rule_data in content.items():
                    if isinstance(rule_data, dict) and "title" in rule_data:
                        fetched.append(f"{rule_id}: {rule_data['title']}")
            except Exception:
                pass
    return fetched


# ---------------------------------------------------------------------------
# Edge routing from decide_node
# Conditional edge functions may return a node name (str) OR list[Send].
# ---------------------------------------------------------------------------

def route_after_decide(state: OrchestratorState):
    """
    Route based on the decide_node output action.
    - direct_response  → str (direct_response_node)
    - ask_user         → str (ask_user_node)
    - dispatch_artifacts → list[Send] — fans out to N parallel run_worker_node calls.

    Returning list[Send] from a conditional edge is the correct LangGraph
    pattern. Nodes must return dict; conditional edges may return list[Send].
    """
    decide_output = state.get("decide_output") or {}
    action = decide_output.get("action", "direct_response")

    if action == "ask_user":
        logger.info("route_after_decide", action="ask_user")
        return "ask_user_node"

    if action == "dispatch_artifacts":
        artifacts = decide_output.get("artifacts", [])[:_MAX_ARTIFACTS]

        logger.info(
            "dispatch_artifacts",
            turn_id=state["turn_id"],
            artifact_count=len(artifacts),
            artifacts=[
                {"type": a.get("artifact_type"), "task": a.get("task_description", "")[:80]}
                for a in artifacts
            ],
        )

        sends: list[Send] = []
        for i, spec in enumerate(artifacts):
            tables_in_scope = spec.get("tables_in_scope", [])
            relevant_rule_ids = spec.get("relevant_business_rule_ids", [])

            prefetched = {
                t: state.get("fetched_table_details", {}).get(
                    t, state["full_metadata"].get("tables", {}).get(t, {})
                )
                for t in tables_in_scope
            }

            all_rules = state["full_metadata"].get("business_rules", [])
            relevant_rules = [
                r for r in all_rules
                if r.get("_id") in relevant_rule_ids or r.get("id") in relevant_rule_ids
            ]

            worker_payload = {
                "turn_id":                   state["turn_id"],
                "worker_id":                 str(i),
                "artifact_type":             spec.get("artifact_type", "table"),
                "chat_id":                   state["chat_id"],
                "database_id":               state["database_id"],
                "schema_name":               state["schema_name"],
                "task_description":          spec.get("task_description", ""),
                "metric_clarification":      spec.get("metric_clarification", ""),
                "suggested_chart_type":      spec.get("suggested_chart_type"),
                "tables_in_scope":           tables_in_scope,
                "relevant_business_rule_ids": relevant_rule_ids,
                "prefetched_context":        prefetched,
                "relevant_business_rules":   relevant_rules,
                "worker_messages":           [],
                "worker_iterations":         0,
                "executed_queries":          [],
                "finalized":                 None,
            }
            sends.append(Send("run_worker_node", worker_payload))

        # Safety: if model returned dispatch but no artifacts, fall back
        if not sends:
            logger.warning("dispatch_artifacts_empty", turn_id=state["turn_id"])
            return "direct_response_node"

        return sends

    logger.info("route_after_decide", action="direct_response")
    return "direct_response_node"

async def direct_response_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)
    model, provider = _model(config)  # Fix: was missing, caused NameError

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
        artifacts=[],           # direct response has no artifacts
        follow_up_questions=follow_ups,
        execution_time_ms=_elapsed_ms(config),
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
    question = decide_output.get("question", "")
    mode = decide_output.get("mode", "free_text")
    options = decide_output.get("options")

    # Handle ask_user_during_discovery path: question lives in the last AI message's tool call
    tool_call_id = None
    for msg in reversed(state.get("discovery_messages", [])):
        for tc in getattr(msg, "tool_calls", []) or []:
            if tc["name"] == "ask_user_during_discovery":
                args = tc.get("args", {})
                if not question:
                    question = args.get("question", "")
                    mode = args.get("mode", "free_text")
                    options = args.get("options") or None
                tool_call_id = tc.get("id")
                break
        if tool_call_id and question:
            break

    if not question:
        question = "Could you clarify your question?"

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

    if not user_answer or user_answer.strip().lower() in ("skip", "__skip__"):
        user_answer = "User did not directly answer — proceed using best judgment and state assumptions made."

    logger.info("ask_user_resumed", chat_id=state["chat_id"])

    # Increment the global ask_user_count (persists across turns via checkpoint)
    current_count = state.get("ask_user_count", 0)

    # ── Critical: close the pending ask_user_during_discovery tool_use block ──
    # Anthropic/Bedrock requires a ToolMessage closing every tool_use block before
    # any subsequent HumanMessage. Without it, every LLM call after resume throws:
    #   ValidationException: tool_use ids found without tool_result blocks immediately after
    # which causes the infinite question loop.
    injected_messages: list = []
    if tool_call_id:
        injected_messages.append(ToolMessage(
            content=json.dumps({"status": "user_answered", "answer": user_answer}),
            tool_call_id=tool_call_id,
            name="ask_user_during_discovery",
        ))
    injected_messages.append(HumanMessage(content=f"Clarification from user: {user_answer}"))

    # Inject the answer back into discovery messages and loop
    return {
        "pending_question": None,
        "ask_user_count": current_count + 1,
        "discovery_messages": injected_messages,
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

    logger.info(
        "dispatch_artifacts",
        turn_id=state["turn_id"],
        artifact_count=len(artifacts),
        artifacts=[
            {"type": a.get("artifact_type"), "task": a.get("task_description", "")[:80]}
            for a in artifacts
        ],
    )

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

    logger.info(
        "join_artifacts",
        turn_id=state["turn_id"],
        total=len(results),
        fresh=fresh,
        errors=errors,
        results=[
            {"title": r.get("title"), "type": r.get("type"), "status": r.get("status"), "note": r.get("note", "")[:80]}
            for r in results
        ],
    )

    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.JOINING_RESULTS,
        status="done",
        title="Charts and Tables Built",
        detail=f"{fresh} visual{'s' if fresh != 1 else ''} ready" + (f" · {errors} couldn't be built" if errors else ""),
        reasoning="",
    ))

    return {}  # state already has artifact_results from workers


# ---------------------------------------------------------------------------
# Node: synthesize_final_node — forced structured output
# ---------------------------------------------------------------------------

async def synthesize_final_node(state: OrchestratorState, config: RunnableConfig) -> dict:
    ws_send, seq_counter, llm_service, *_ = await _get_ws(config)

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

    # Recent conversation context (last 3 turns, compact)
    recent_context = _format_recent_turns(
        state.get("recent_turns", [])[-3:]
    ) if state.get("recent_turns") else "No prior conversation."

    # Key findings from discovery phase
    key_findings = state.get("discovery_key_findings", "")
    key_findings_block = f"\nDiscovery key findings:\n{key_findings}" if key_findings else ""

    synth_messages = [
        SystemMessage(content=SYNTHESIZE_SYSTEM),
        HumanMessage(content=(
            f"User's original question: {state['user_message']}\n\n"
            f"Recent conversation context:\n{recent_context}"
            f"{key_findings_block}\n\n"
            f"Artifact results:\n{results_summary}\n\n"
            'Return JSON: {"markdown": "...", "follow_up_questions": ["...", "...", "..."], "step_title": "...", "reasoning": "..."}'
        )),
    ]

    # Log messages being passed to synthesize LLM
    logger.info(
        "synthesize_node_messages",
        turn_id=state["turn_id"],
        message_count=len(synth_messages),
        artifact_count=len(results),
        messages_preview=[
            {"role": type(m).__name__, "content_preview": (m.content if isinstance(m.content, str) else str(m.content))[:300]}
            for m in synth_messages
        ],
    )

    markdown = ""
    follow_ups: list[str] = []
    reasoning_text = ""

    try:
        model, provider = _model(config)
        logger.info(
            "synthesize_llm_call",
            turn_id=state["turn_id"],
            model=model,
            artifact_count=len(results),
        )
        response: AIMessage = await llm_service.ainvoke(
            synth_messages,
            model=model,
            max_tokens=2048,
            temperature=0.3,
            provider=provider,
        )
        reasoning_text = _extract_reasoning(response)  # thinking blocks if present
        content = response.content if isinstance(response.content, str) else ""
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(content)
        markdown = parsed.get("markdown", "")
        follow_ups = parsed.get("follow_up_questions", [])[:3]
        # Pull LLM-generated title + reasoning from JSON output
        synth_step_title = parsed.get("step_title", "")
        llm_reasoning = parsed.get("reasoning", "")
        if llm_reasoning:
            reasoning_text = llm_reasoning  # prefer explicit reasoning over thinking blocks
        logger.info(
            "synthesize_output",
            turn_id=state["turn_id"],
            step_title=synth_step_title,
            markdown_len=len(markdown),
            follow_up_count=len(follow_ups),
            follow_ups=follow_ups,
            reasoning=reasoning_text,
        )
    except Exception as exc:
        logger.warning("synthesize_parse_error", turn_id=state["turn_id"], error=str(exc))
        # Fallback markdown
        fresh_results = [r for r in results if r["status"] == "fresh"]
        lines = ["Here is your analysis:"]
        for r in fresh_results:
            lines.append(f"\n**{r['title']}**: {r['note']}")
        markdown = "\n".join(lines)
        follow_ups = []
        synth_step_title = ""

    # Build the full artifact payload list for the WS event
    artifacts_payload = [
        {
            "artifact_id":   r["artifact_id"],
            "type":          r["type"],
            "title":         r["title"],
            "note":          r["note"],
            "key_numbers":   r["key_numbers"],
            "status":        r["status"],
            "error_message": r.get("error_message"),
            "config":        r.get("config", {}),
            "result_data":   r.get("result_data", []),
            "sql_query":     r.get("sql_query", ""),
        }
        for r in results
        if r["status"] == "fresh"
    ]
    artifact_ids = [r["artifact_id"] for r in results if r["status"] == "fresh"]

    # Emit synthesize done step — use LLM-generated title when available
    seq = await seq_counter.next()
    await ws_send(make_step(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        name=StepName.SYNTHESIZING,
        status="done",
        title=synth_step_title or "Your Analysis Is Ready",
        detail=f"{len(artifact_ids)} visual{'s' if len(artifact_ids) != 1 else ''} with full insights",
        reasoning=reasoning_text,  # full, untruncated
    ))

    seq = await seq_counter.next()
    await ws_send(make_final(
        chat_id=state["chat_id"],
        turn_id=state["turn_id"],
        seq=seq,
        markdown=markdown,
        artifacts=artifacts_payload,
        follow_up_questions=follow_ups,
        execution_time_ms=_elapsed_ms(config),
    ))

    return {
        "final_markdown": markdown,
        "follow_up_questions": follow_ups,
    }


# ---------------------------------------------------------------------------
# Helper: generate follow-up questions for direct responses
# ---------------------------------------------------------------------------

async def _generate_follow_ups(
    user_message: str,
    markdown: str,
    llm_service: Any,
    model: str,
    provider: str | None = None,
) -> list[str]:
    try:
        response: AIMessage = await llm_service.ainvoke(
            [
                SystemMessage(content=(
                    "You are generating suggested follow-up questions for a business analytics chat.\n\n"
                    "These questions will appear as clickable buttons the user can select to run next.\n"
                    "They must read like something the USER would type — direct, specific, ready to execute.\n\n"
                    "STRICT RULES:\n"
                    "  ✓ Write from the user's perspective (e.g. 'Show me revenue by region' not 'Would you like revenue by region?')\n"
                    "  ✓ Be specific — include metric name, dimension, or time period where relevant\n"
                    "  ✓ Extend or deepen the current topic (drill down, new dimension, related metric)\n"
                    "  ✓ GOOD: \"Show me monthly revenue trend for the last 6 months\"\n"
                    "  ✓ GOOD: \"Which product category had the highest margin last quarter?\"\n"
                    "  ✓ GOOD: \"Break down customer churn by acquisition channel\"\n"
                    "  ✗ BAD: \"What metrics would you like to analyze?\" — preference question, NEVER do this\n"
                    "  ✗ BAD: \"Would you like more details?\" — vague, NEVER do this\n"
                    "  ✗ BAD: \"What time period are you interested in?\" — meta question, NEVER do this\n"
                    "  ✗ BAD: \"What specific business metrics or KPIs would you like to analyze first?\" — NEVER\n\n"
                    "Return ONLY a JSON array of exactly 2 strings: [\"...\", \"...\"]"
                )),
                HumanMessage(content=(
                    f"User's message: {user_message}\n"
                    f"Nirnaya's response: {markdown[:600]}\n\n"
                    "Generate 2 ready-to-run follow-up questions the user can click next:"
                )),
            ],
            model=model,
            max_tokens=256,
            temperature=0.4,
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
    graph.add_node("shortcut_decide_node", shortcut_decide_node)  # fast path: skips decide LLM
    graph.add_node("decide_node", decide_node)
    graph.add_node("direct_response_node", direct_response_node)
    graph.add_node("ask_user_node", ask_user_node)
    # dispatch is handled via Send in route_after_decide (conditional edge) — no node needed
    graph.add_node("run_worker_node", run_worker_node)
    graph.add_node("join_artifacts_node", join_artifacts_node)
    graph.add_node("synthesize_final_node", synthesize_final_node)

    # ── Edges ─────────────────────────────────────────────────────────
    graph.add_edge(START, "skim_tables")
    graph.add_edge("skim_tables", "discovery_loop")

    graph.add_conditional_edges(
        "discovery_loop",
        route_after_discovery,
        {
            "tool_executor": "tool_executor",
            "shortcut_decide_node": "shortcut_decide_node",
            "decide_node": "decide_node",
            "ask_user_node": "ask_user_node",  # ask_user_during_discovery tool path
        },
    )
    graph.add_edge("tool_executor", "discovery_loop")
    # shortcut_decide_node skips the decide LLM — goes straight to route_after_decide
    graph.add_conditional_edges(
        "shortcut_decide_node",
        route_after_decide,
        {
            "direct_response_node": "direct_response_node",
            "ask_user_node": "ask_user_node",
        },
    )

    graph.add_conditional_edges(
        "decide_node",
        route_after_decide,
        {
            # String returns map to node names;
            # list[Send] returns (for dispatch_artifacts) are handled directly by LangGraph.
            "direct_response_node": "direct_response_node",
            "ask_user_node": "ask_user_node",
        },
    )

    # direct_response → END
    graph.add_edge("direct_response_node", END)

    # ask_user_node pauses via interrupt(); on resume → back to discovery_loop
    graph.add_edge("ask_user_node", "discovery_loop")

    # route_after_decide returns list[Send("run_worker_node", ...)] for dispatch_artifacts;
    # all workers automatically flow to join_artifacts_node via the edge below.
    graph.add_edge("run_worker_node", "join_artifacts_node")
    graph.add_edge("join_artifacts_node", "synthesize_final_node")
    graph.add_edge("synthesize_final_node", END)

    return graph.compile(checkpointer=checkpointer)

