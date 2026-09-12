"""
app/websocket/sql_chat_agent/entrypoint.py
-------------------------------------------
handle_chat_agent — called from ws_agent.py for every ChatAgent WS frame.

Responsibilities
────────────────
1. Load database record + metadata from Supabase Storage
2. Fetch recent chat history (last 5 turns)
3. Auto-generate chat title if chat has no title (fire-and-forget small LLM call)
4. Build OrchestratorState
5. Run/resume the compiled orchestrator graph
6. Persist the user message and assistant response to chat_messages table
7. Clean up checkpoint after turn completes

Resume flow (reconnect)
────────────────────────
If the client sends { requestType: "resume", turn_id, last_seq }, ws_agent.py
replays events from the Redis stream buffer (stream:{turn_id}) for seq > last_seq.
No entrypoint re-invocation needed.

ask_user_response flow
───────────────────────
If the client sends { requestType: "ask_user_response", turn_id, answer },
ws_agent.py calls handle_ask_user_response() which resumes the graph via
Command(resume=answer).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.core.logging import get_logger
from app.services.chat_service import ChatService
from app.services.redis_service import RedisService
from app.services.supabase_service import SupabaseService
from app.services.project_service import ProjectService
from .events import STREAM_TTL_SECONDS, make_error, make_step, stream_key, StepName
from .orchestrator_graph import build_orchestrator_graph

logger = get_logger(__name__)

# Redis key for pending turn context (ask_user interrupt)
_PENDING_TURN_PREFIX = "nirnaya:cache:pending_turn:"

BUCKET = "nirnaya-sessions"


# ---------------------------------------------------------------------------
# SeqCounter — monotonic, asyncio-safe
# ---------------------------------------------------------------------------

class SeqCounter:
    """Thread-safe monotonic sequence counter for WS step events."""

    def __init__(self, start: int = 0) -> None:
        self._val = start
        self._lock = asyncio.Lock()

    async def next(self) -> int:
        async with self._lock:
            self._val += 1
            return self._val

    @property
    def current(self) -> int:
        return self._val


# ---------------------------------------------------------------------------
# WS sender with Redis stream buffering
# ---------------------------------------------------------------------------

def make_ws_sender(
    ws_send_raw: Callable[[str], Coroutine],
    redis_service: RedisService,
    turn_id: str,
    steps_log: list[dict] | None = None,
) -> Callable[[dict], Coroutine]:
    """
    Wraps the raw WS send function:
    - Serialises event dict to JSON
    - Appends to Redis stream for replay on reconnect (TTL: 30 min)
    - If steps_log is provided, silently accumulates every `step` event
      (compact form) so the caller can persist them to DB after the turn.
    - Swallows send errors (client may have disconnected)
    """
    async def _send(event: dict) -> None:
        # Accumulate step events for DB persistence (only the fields FE needs)
        if steps_log is not None and event.get("type") == "step":
            steps_log.append({
                "seq":         event.get("seq"),
                "name":        event.get("name"),
                "status":      event.get("status"),
                "title":       event.get("title"),
                "detail":      event.get("detail"),
                "reasoning":   event.get("reasoning", ""),
                "artifact_id": event.get("artifact_id"),
                "worker_id":   event.get("worker_id"),
                "ts":          event.get("ts"),
            })

        payload = json.dumps(event)
        try:
            key = stream_key(turn_id)
            await redis_service.client.rpush(key, payload)
            await redis_service.client.expire(key, STREAM_TTL_SECONDS)
        except Exception:
            pass
        try:
            await ws_send_raw(payload)
        except Exception:
            pass

    return _send


# ---------------------------------------------------------------------------
# Metadata loader — Supabase Storage
# ---------------------------------------------------------------------------

async def _load_metadata_from_storage(
    session_id: str,
    database_id: str,
    supabase_service: SupabaseService,
) -> dict:
    """
    Load the metadata JSON from Supabase Storage.
    Path: {session_id}/metadata/{database_id}.json
    """
    path = f"{session_id}/metadata/{database_id}.json"
    try:
        raw = await supabase_service.admin.storage.from_(BUCKET).download(path)
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw)
    except Exception as exc:
        logger.warning("metadata_storage_load_failed", path=path, error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# Database context loader
# ---------------------------------------------------------------------------

async def _get_database_record(
    database_id: str,
    session_id: str,
    supabase_service: SupabaseService,
) -> dict | None:
    """Get the database record (schema_name, name) from Supabase."""
    try:
        resp = (
            await supabase_service.admin.table("databases")
            .select("id, schema_name, name, session_id")
            .eq("id", database_id)
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
        return resp.data
    except Exception as exc:
        logger.warning("get_database_record_failed", database_id=database_id, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Recent turns loader
# ---------------------------------------------------------------------------

async def _load_recent_turns(
    project_id: str,
    session_id: str,
    supabase_service: SupabaseService,
) -> list[dict]:
    """
    Load and compact the last 5 *completed* turns for this project.
    Queries chat_messages by project_id (oldest-first after limit reversal).
    Each DB row = one turn with user_message + output fields.
    """
    chat_svc = ChatService(session_id, supabase_service)
    rows = await chat_svc.get_recent_turns(project_id, limit=5)

    turns: list[dict] = []
    for row in rows:
        turns.append({"role": "user", "text": row.get("user_message", "")})
        output = row.get("output") or {}
        if output:
            turns.append({
                "role": "assistant",
                "content": {"markdown": output.get("markdown", "")[:400]},
                "artifact_titles": output.get("artifact_ids", []),
            })

    logger.info(
        "recent_turns_loaded",
        project_id=project_id,
        raw_rows=len(rows),
        turns_built=len(turns),
        turns=turns,   # log full content so we can verify what goes into the prompt
    )
    return turns


# ---------------------------------------------------------------------------
# Auto title generator — silent, fire-and-forget
# ---------------------------------------------------------------------------

async def _auto_generate_project_title(
    *,
    project_id: str,
    user_message: str,
    llm_service: Any,
    provider: str | None,
    ws_send: Callable[[dict], Coroutine],
    project_service: ProjectService,
) -> None:
    """
    Generate a short project title from the first user message and persist it
    to the projects table via ProjectService.update_title.
    Sends a 'project_title_updated' WS event so FE can update the sidebar.

    Always uses the cheapest available model via llm_service.generate_title()
    regardless of what model the agent is using — avoids the agent model being
    invoked with a tiny max_tokens budget and returning a truncated reply as the
    title.

    Called as asyncio.create_task() — does NOT block the main graph execution.
    Fires only for the first turn of a project (no prior completed turns).
    """
    try:
        title = await llm_service.generate_title(
            user_message=user_message,
            provider=provider,
        )
        if not title:
            return

        # Persist title to the projects table
        await project_service.update_title(project_id, title)

        # Notify FE — not a step event, just a sidebar metadata update
        await ws_send({
            "type": "project_title_updated",
            "project_id": project_id,
            "title": title,
        })

        logger.info("project_title_generated", project_id=project_id, title=title)

    except Exception as exc:
        # Non-fatal — title is optional
        logger.info("project_title_generation_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Main entry point: handle a ChatAgent WS frame
# ---------------------------------------------------------------------------

async def handle_chat_agent(
    *,
    session_id: str,
    project_id: str,
    chat_id: str,
    user_message: str,
    turn_id: str,
    model: str,
    provider: str | None,
    ws_send_raw: Callable[[str], Coroutine],
    supabase_service: SupabaseService,
    redis_service: RedisService,
    checkpointer: Any,
) -> None:
    """
    Full turn lifecycle for a single user message.
    Called by ws_agent.py as an asyncio.Task.
    Streams step/ask_user/final events over the WebSocket.
    """
    from app.services.llm_service import LLMService
    from app.services.project_service import ProjectService
    from app.services.session_service import SessionService

    chat_svc = ChatService(session_id, supabase_service)
    seq_counter = SeqCounter()
    steps_log: list[dict] = []  # collects every step event for DB persistence
    ws_send = make_ws_sender(ws_send_raw, redis_service, turn_id, steps_log)
    turn_start_ms: int = int(time.monotonic() * 1000)  # monotonic clock, milliseconds

    # chat_id = turn_id: each turn is its own checkpointer thread.
    # The project_id groups all turns for context/history.
    chat_id = turn_id

    # ── 1. Resolve project → database_id ──────────────────────────────
    try:
        project_svc = ProjectService(session_id, supabase_service)
        project_record = await project_svc.get(project_id)
        if not project_record:
            await ws_send(make_error(
                chat_id=chat_id, turn_id=turn_id,
                seq=await seq_counter.next(),
                message=f"Project '{project_id}' not found or not accessible.",
            ))
            return
        database_id: str = project_record.get("database_id", "")
    except Exception as exc:
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"Project '{project_id}' not found or not accessible.",
        ))
        logger.warning("project_lookup_failed", project_id=project_id, error=str(exc))
        return

    if not database_id:
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message="Project has no database attached. Please upload data files first.",
        ))
        return

    # ── 2. Persist turn row (output=NULL; filled after graph completes) ──
    # chat_messages.id = turn_id — used as the LangGraph checkpointer thread_id.
    try:
        await chat_svc.create_turn(
            project_id=project_id,
            user_message=user_message,
            turn_id=turn_id,
            database_id=database_id,
        )
    except Exception as exc:
        logger.warning("turn_create_failed", turn_id=turn_id, error=str(exc))

    # ── 4. Load database record ───────────────────────────────────────
    db_record = await _get_database_record(database_id, session_id, supabase_service)
    if not db_record:
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"Database '{database_id}' not found or not accessible.",
        ))
        return

    schema_name = db_record.get("schema_name")
    if not schema_name:
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"Database record corrupted: missing schema_name.",
        ))
        return

    # ── 5. Load metadata ──────────────────────────────────────────────
    full_metadata = await _load_metadata_from_storage(session_id, database_id, supabase_service)

    if not full_metadata.get("tables"):
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message="No table metadata found. Please upload data files first.",
        ))
        return

    # ── 5. Build summary views from metadata ──────────────────────────────
    tables_overview = {
        name: {
            "overview":    info.get("overview", ""),
            "key_columns": info.get("key_columns", []),
            "grain":       info.get("grain", ""),
            "domain_tags": info.get("domain_tags", []),
            "row_count":   info.get("row_count", 0),
        }
        for name, info in full_metadata.get("tables", {}).items()
    }
    business_rules_index = [
        {"_id": r.get("_id", r.get("id", "")), "title": r.get("title", "")}
        for r in full_metadata.get("business_rules", [])
    ]

    # ── 6. Load recent turns (by project_id) ────────────────────────────────
    recent_turns = await _load_recent_turns(project_id, session_id, supabase_service)

    # ── 7. Build LLM service ─────────────────────────────────────────────────
    session_svc = SessionService(redis_service)
    llm_service = LLMService.from_session(session_id, session_svc)

    # ── 8. Auto-title project (fire-and-forget) ──────────────────────────────
    # Fires only for the first turn of a project (no prior completed turns).
    # Reuses the main llm_service; result goes to projects table + WS event.
    if not project_record.get("title") or project_record.get("title") == "Untitled":
        asyncio.create_task(_auto_generate_project_title(
            project_id=project_id,
            user_message=user_message,
            llm_service=llm_service,
            provider=provider,
            ws_send=ws_send,
            project_service=project_svc,
        ))

    # ── 9. Build initial state ─────────────────────────────────────────────────
    # chat_id = turn_id (each turn is its own checkpointer thread).
    # project_id groups all turns for context/history.
    initial_state: dict = {
        "chat_id":              chat_id,           # = turn_id
        "turn_id":              turn_id,
        "session_id":           session_id,
        "project_id":           project_id,
        "database_id":          database_id,
        "schema_name":          schema_name,
        "user_message":         user_message,
        "recent_turns":         recent_turns,
        "tables_overview":      tables_overview,
        "business_rules_index": business_rules_index,
        "full_metadata":        full_metadata,
        "discovery_messages":   [],
        "discovery_iterations": 0,
        "fetched_table_details":{},
        "discovery_results":    [],
        "decide_output":        None,
        "pending_question":     None,
        "dispatch_plan":        None,
        "artifact_results":     [],
        "final_markdown":       None,
        "follow_up_questions":  None,
    }

    # ── 10. Build LangGraph config ────────────────────────────────────────────────
    # thread_id = turn_id (= chat_id) so each turn is independently checkpointable.
    # turn_message_id is passed so workers can link artifacts to the right row.
    # turn_start_ms is the monotonic clock in ms at turn creation — nodes use this
    # to compute execution_time_ms for the final WS event and DB update.
    thread_config: RunnableConfig = {
        "configurable": {
            "thread_id":        turn_id,           # checkpointer key = chat_messages.id
            "model":            model,
            "provider":         provider,
            "ws_send":          ws_send,
            "seq_counter":      seq_counter,
            "llm_service":      llm_service,
            "supabase_service": supabase_service,
            "redis_service":    redis_service,
            "chat_service":     chat_svc,
            "full_metadata":    full_metadata,
            "effective_db_id":  database_id,
            "project_id":       project_id,
            "turn_message_id":  turn_id,           # = chat_messages.id for artifact FK
            "turn_start_ms":    turn_start_ms,     # monotonic ms — for execution_time_ms
        }
    }

    # ── 11. Compile + run graph ───────────────────────────────────────
    compiled_graph = build_orchestrator_graph(checkpointer=checkpointer)

    final_markdown = ""
    follow_up_questions: list[str] = []
    artifact_ids: list[str] = []

    try:
        result = await compiled_graph.ainvoke(initial_state, config=thread_config)
        final_markdown      = result.get("final_markdown", "")
        follow_up_questions = result.get("follow_up_questions", [])
        artifact_ids = [
            r["artifact_id"]
            for r in result.get("artifact_results", [])
            if r.get("status") == "fresh"
        ]
    except Exception as exc:
        logger.error("orchestrator_graph_error", turn_id=turn_id, error=str(exc))
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"An error occurred: {str(exc)[:300]}",
        ))
        return

    # ── 11. Fill in turn output (answer side of the single row) ──────
    elapsed_ms: int = int(time.monotonic() * 1000) - turn_start_ms
    try:
        await chat_svc.update_turn_output(
            turn_id=turn_id,
            output={
                "markdown":            final_markdown,
                "artifact_ids":        artifact_ids,
                "follow_up_questions": follow_up_questions,
                "execution_time_ms":   elapsed_ms,
                "steps":               steps_log,   # ordered list of step events
            },
        )
    except Exception as exc:
        logger.warning("turn_output_update_failed", error=str(exc))

    # ── 12. Clean up checkpoint ───────────────────────────────────────
    if checkpointer:
        try:
            await checkpointer.adelete({"configurable": {"thread_id": turn_id}})
        except Exception:
            pass

    await redis_service.cache_delete(f"pending_turn:{turn_id}")

    logger.info(
        "turn_complete",
        turn_id=turn_id,
        model=model,
        artifact_count=len(artifact_ids),
        seq=seq_counter.current,
    )


# ---------------------------------------------------------------------------
# Resume handler — ask_user_response
# ---------------------------------------------------------------------------

async def handle_ask_user_response(
    *,
    session_id: str,
    turn_id: str,
    answer: str,
    model: str,
    provider: str | None,
    ws_send_raw: Callable[[str], Coroutine],
    supabase_service: SupabaseService,
    redis_service: RedisService,
    checkpointer: Any,
) -> None:
    """
    Resume an interrupted graph turn with the user's clarification answer.
    Called from ws_agent.py when { requestType: "ask_user_response" } is received.
    """
    from app.services.llm_service import LLMService
    from app.services.session_service import SessionService

    pending_raw = await redis_service.cache_get(f"pending_turn:{turn_id}")
    if not pending_raw:
        logger.warning("ask_user_response_no_pending_turn", turn_id=turn_id)
        try:
            await ws_send_raw(json.dumps({"type": "error", "message": "No pending question found for this turn."}))
        except Exception:
            pass
        return

    pending: dict = pending_raw if isinstance(pending_raw, dict) else {}
    chat_id = pending.get("chat_id", "")
    thread_config = pending.get("config", {})

    if not chat_id or not checkpointer:
        return

    seq_counter = SeqCounter(start=pending.get("seq", 10))
    ws_send = make_ws_sender(ws_send_raw, redis_service, turn_id)

    session_svc = SessionService(redis_service)
    llm_service = LLMService.from_session(session_id, session_svc)
    chat_svc = ChatService(session_id, supabase_service)

    thread_config.setdefault("configurable", {})
    thread_config["configurable"].update({
        "model":            model,
        "provider":         provider,
        "ws_send":          ws_send,
        "seq_counter":      seq_counter,
        "llm_service":      llm_service,
        "supabase_service": supabase_service,
        "redis_service":    redis_service,
        "chat_service":     chat_svc,
        "full_metadata":    pending.get("full_metadata", {}),
    })

    compiled_graph = build_orchestrator_graph(checkpointer=checkpointer)

    try:
        await compiled_graph.ainvoke(Command(resume=answer), config=thread_config)
    except Exception as exc:
        logger.error("ask_user_resume_error", turn_id=turn_id, error=str(exc))
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"Failed to resume: {str(exc)[:200]}",
        ))

    await redis_service.cache_delete(f"pending_turn:{turn_id}")
