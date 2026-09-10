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
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.core.logging import get_logger
from app.services.chat_service import ChatService
from app.services.redis_service import RedisService
from app.services.supabase_service import SupabaseService

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
) -> Callable[[dict], Coroutine]:
    """
    Wraps the raw WS send function:
    - Serialises event dict to JSON
    - Appends to Redis stream for replay on reconnect (TTL: 30 min)
    - Swallows send errors (client may have disconnected)
    """
    async def _send(event: dict) -> None:
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
    chat_id: str,
    session_id: str,
    supabase_service: SupabaseService,
) -> list[dict]:
    """Load and compact the last 10 messages for prompt context."""
    chat_svc = ChatService(session_id, supabase_service)
    messages = await chat_svc.get_recent_messages(chat_id, limit=10)

    turns: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", {})
        if role == "user":
            turns.append({"role": "user", "text": content.get("text", "")})
        elif role == "assistant":
            turns.append({
                "role": "assistant",
                "markdown": content.get("markdown", "")[:400],
                "artifact_titles": content.get("artifact_ids", []),
            })
    return turns


# ---------------------------------------------------------------------------
# Auto title generator — silent, fire-and-forget
# ---------------------------------------------------------------------------

async def _auto_generate_title(
    *,
    chat_id: str,
    user_message: str,
    session_id: str,
    llm_service: Any,
    model: str,
    provider: str | None,
    ws_send: Callable[[dict], Coroutine],
    supabase_service: SupabaseService,
) -> None:
    """
    Generate a short chat title from the first user message and persist it.
    Sends a 'chat_title_updated' WS event (not a step — doesn't appear in
    the step log or progress indicator).

    Called as asyncio.create_task() — does NOT block the main graph execution.
    """
    try:
        response = await llm_service.ainvoke(
            [
                SystemMessage(content=(
                    "Generate a concise chat title (5-8 words, no punctuation, title case) "
                    "that describes what the following analytics question is about. "
                    "Return ONLY the title, nothing else."
                )),
                HumanMessage(content=user_message[:400]),
            ],
            model=model,
            max_tokens=30,
            temperature=0.3,
            provider=provider,
        )
        title = response.content.strip().strip('"\'') if hasattr(response, "content") else ""
        if not title:
            return

        # Persist title to the chats table
        chat_svc = ChatService(session_id, supabase_service)
        await chat_svc.update_chat_title(chat_id, title)

        # Notify FE — this is NOT a step event, just a metadata update
        await ws_send({
            "type": "chat_title_updated",
            "chat_id": chat_id,
            "title": title,
        })

        logger.debug("chat_title_generated", chat_id=chat_id, title=title)

    except Exception as exc:
        # Non-fatal — title is optional
        logger.debug("chat_title_generation_failed", error=str(exc))


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
    ws_send = make_ws_sender(ws_send_raw, redis_service, turn_id)

    # ── 1. Resolve project → database_id ──────────────────────────────
    # The FE sends project_id only. We fetch the project row to get database_id.
    try:
        project_svc = ProjectService(session_id, supabase_service)
        project_record = await project_svc.get(project_id)
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

    # ── 2. Ensure chat row exists (create if new conversation) ────────
    existing_chat = await chat_svc.get_chat(chat_id)
    if not existing_chat:
        try:
            await chat_svc.create_chat(
                database_id=database_id,
                project_id=project_id,
                chat_id=chat_id,
            )
        except Exception as exc:
            logger.warning("chat_row_create_failed", chat_id=chat_id, error=str(exc))

    # ── 3. Persist user message ───────────────────────────────────────
    try:
        await chat_svc.add_message(
            chat_id=chat_id,
            role="user",
            content={"text": user_message},
        )
    except Exception as exc:
        logger.warning("user_message_persist_failed", error=str(exc))

    # ── 4. Load database record ───────────────────────────────────────
    db_record = await _get_database_record(database_id, session_id, supabase_service)
    if not db_record:
        await ws_send(make_error(
            chat_id=chat_id, turn_id=turn_id,
            seq=await seq_counter.next(),
            message=f"Database '{database_id}' not found or not accessible.",
        ))
        return
    schema_name: str = db_record["schema_name"]

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

    # ── 6. Load recent turns ─────────────────────────────────────────────────
    recent_turns = await _load_recent_turns(chat_id, session_id, supabase_service)

    # ── 7. Auto-title (silent, non-blocking) ─────────────────────────────
    # Fire when this is a brand-new chat (existing_chat was None) so title is
    # always set on the first message and never re-set on followup turns.
    if not existing_chat and not recent_turns:
        session_svc_title = SessionService(redis_service)
        llm_service_title = LLMService.from_session(session_id, session_svc_title)
        asyncio.create_task(_auto_generate_title(
            chat_id=chat_id,
            user_message=user_message,
            session_id=session_id,
            llm_service=llm_service_title,
            model=model,
            provider=provider,
            ws_send=ws_send,
            supabase_service=supabase_service,
        ))

    # ── 8. Build LLM service ─────────────────────────────────────────────────
    session_svc = SessionService(redis_service)
    llm_service = LLMService.from_session(session_id, session_svc)

    # ── 9. Build initial state ─────────────────────────────────────────────────
    initial_state: dict = {
        "chat_id":              chat_id,
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
    thread_config: RunnableConfig = {
        "configurable": {
            "thread_id":        chat_id,          # checkpointer key
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
        }
    }

    # ── 11. Compile + run graph ───────────────────────────────────────
    compiled_graph = build_orchestrator_graph(checkpointer=checkpointer)

    final_markdown = ""
    follow_up_questions: list[str] = []
    artifact_ids: list[str] = []

    try:
        result = await compiled_graph.ainvoke(initial_state, config=thread_config)
        final_markdown       = result.get("final_markdown", "")
        follow_up_questions  = result.get("follow_up_questions", [])
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

    # ── 11. Persist assistant message ─────────────────────────────────
    try:
        await chat_svc.add_message(
            chat_id=chat_id,
            role="assistant",
            content={
                "markdown":             final_markdown,
                "steps":                [],
                "artifact_ids":         artifact_ids,
                "follow_up_questions":  follow_up_questions,
            },
        )
    except Exception as exc:
        logger.warning("assistant_message_persist_failed", error=str(exc))

    # ── 12. Clean up checkpoint ───────────────────────────────────────
    if checkpointer:
        try:
            await checkpointer.adelete({"configurable": {"thread_id": chat_id}})
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
