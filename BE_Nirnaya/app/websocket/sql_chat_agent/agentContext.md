# Nirnaya SQL Chat Agent — Context & Changelog

## Purpose
This document tracks the architecture, key decisions, and environment requirements
for the LangGraph-based SQL analytics agent in `BE_Nirnaya/app/websocket/sql_chat_agent/`.

---

## Setup Checklist (One-time)

### 1. Install new dependencies
```bash
cd BE_Nirnaya
pip install -r requirements.txt
```
New packages added: `langgraph>=0.2.0`, `langgraph-checkpoint-postgres>=2.0.0`,
`psycopg[binary]>=3.1.0`, `psycopg-pool>=3.1.0`

### 2. Add `DATABASE_URL` to `.env` (optional but recommended)

> **If not set, the agent uses `MemorySaver` — interrupt/resume still works within
> the same server process. State is lost if the server restarts mid-conversation.**

If you want persistent checkpointing, use the **Session Pooler URL** (NOT the direct URL):
```
# ❌ WRONG — direct connection, fails on most networks without IPv4 Add-On:
# DATABASE_URL=postgresql://postgres:PW@db.PROJECT.supabase.co:5432/postgres

# ✅ CORRECT — Session Pooler URL:
DATABASE_URL=postgresql://postgres.PROJECT:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
```
Find it at: **Supabase → Settings → Database → Connection Pooling → Session mode → URI**

> The LangGraph checkpointer auto-creates its 4 tables on first startup. No manual SQL needed.

### 3. New Supabase tables (auto-created at startup)
The following tables are created automatically by `ChatService.initialize_chat_tables()`:
- `public.chats` — one row per conversation within a database
- `public.chat_messages` — user + assistant messages with JSONB content
- `public.artifacts` — kpi/chart/table artifacts with full result_data
  - `database_id` is **nullable** — NULL for demo database artifacts (no FK row)

---

## Demo Database

| Property | Value |
|---|---|
| `database_id` in WS frame | `"Music E-commerce"` (name string, **not a UUID**) |
| Metadata source | `BE_Nirnaya/demo_database.json` (local file, process-cached) |
| Schema in Postgres | `demo` |
| `artifacts.database_id` | `NULL` (FK nullable) |
| Session row required? | **No** — no `databases` table row needed |

The FE never looks up a demo database UUID — it just sends the name. The agent
detects `database_id == "Music E-commerce"` and routes accordingly.

---

## File Map

```
app/websocket/
├── ws_agent.py                   ← Modified: ChatAgent + ask_user_response + resume routing
└── sql_chat_agent/
    ├── __init__.py               ← Exports handle_chat_agent
    ├── agentContext.md           ← This file
    ├── state.py                  ← OrchestratorState, WorkerState, ArtifactResult TypedDicts
    ├── events.py                 ← WS event builders (step/ask_user/final/error)
    ├── sql_executor.py           ← SQL execution + security checks + Redis caching
    ├── prompts.py                ← System prompt builders (orchestrator + worker)
    ├── tools_orchestrator.py     ← Orchestrator tools (get_table_details, run_discovery_queries, etc.)
    ├── tools_worker.py           ← Worker tools (run_sql, finalize_kpi/chart/table)
    ├── worker_graph.py           ← Worker logic (explore_loop → finalize → promote)
    ├── orchestrator_graph.py     ← Full LangGraph StateGraph
    └── entrypoint.py             ← handle_chat_agent + handle_ask_user_response

app/services/
├── checkpointer_service.py       ← New: AsyncPostgresSaver wrapper
└── chat_service.py               ← New: chats/chat_messages/artifacts CRUD
```

---

## LangGraph Concepts Used

| Concept | Where | Purpose |
|---|---|---|
| `StateGraph` | `orchestrator_graph.py` | Typed state flowing through nodes |
| `add_messages` reducer | `OrchestratorState.discovery_messages` | Appends LLM messages without duplicating |
| `operator.add` reducer | `OrchestratorState.artifact_results` | Parallel workers safely append results |
| Conditional edges | `route_after_discovery`, `route_after_decide` | Dynamic routing based on LLM output |
| `Send` | `dispatch_artifacts_node` | Fan-out to N parallel worker nodes |
| `interrupt()` | `ask_user_node` | Pauses graph; resumes via `Command(resume=answer)` |
| `AsyncPostgresSaver` | `CheckpointerService` | Persists state for interrupt/resume |
| `RunnableConfig["configurable"]` | All nodes | Passes non-serializable objects (ws_send, services) |

---

## WebSocket Protocol

### Server → Client events
```jsonc
// Step event (one per discrete action)
{
  "type": "step",
  "chat_id": "uuid",
  "turn_id": "uuid",
  "seq": 4,
  "name": "running_discovery",       // StepName constant
  "status": "in_progress" | "done" | "error",
  "title": "Exploring Schema",        // Human-readable title
  "detail": "Running 2 discovery queries...",
  "reasoning": "Need to check revenue definition",
  "artifact_id": null,
  "worker_id": null,
  "ts": "2026-09-10T12:00:00Z"
}

// Clarifying question (pauses graph)
{
  "type": "ask_user",
  "chat_id": "uuid",
  "turn_id": "uuid",
  "seq": 7,
  "question": "Should revenue include refunds?",
  "mode": "mcq" | "free_text",
  "options": ["Yes", "No"] | null,
  "ts": "..."
}

// Terminal event
{
  "type": "final",
  "chat_id": "uuid",
  "turn_id": "uuid",
  "seq": 12,
  "markdown": "## Revenue Analysis\n...",
  "artifact_ids": ["uuid", "uuid"],
  "follow_up_questions": ["What is...", "How does..."],
  "ts": "..."
}
```

### Client → Server events
```jsonc
{ "requestType": "ChatAgent", "transactionId": "uuid", "chat_id": "uuid", "database_id": "uuid", "text": "What is total revenue?" }
{ "requestType": "ask_user_response", "transactionId": "uuid", "turn_id": "uuid", "answer": "Monthly, USD only" }
{ "requestType": "resume", "transactionId": "uuid", "turn_id": "uuid", "last_seq": 6 }
{ "requestType": "ping", "transactionId": "uuid" }
```

---

## Orchestrator Graph Flow

```
START → skim_tables → discovery_loop ⇄ tool_executor → decide_node
                                                              │
                         ┌────────────────┬─────────────────┘
                         │                │                  │
                   direct_response  ask_user_node    dispatch_artifacts
                         │           (interrupt)          │
                        END          │                [Send × N]
                                     ▼                     │
                                discovery_loop        run_worker × N
                                                           │
                                                    join_artifacts
                                                           │
                                                   synthesize_final → END
```

---

## Security

- **Schema ownership check**: All SQL is validated to only reference the session's authorized schema (`n_XXXX_dbname`). Cross-schema access is blocked.
- **Row cap**: Fetch limit 5001 rows (detect truncation), store limit 1000 rows in `artifacts.result_data`, preview 20 rows to LLM.
- **No `SET search_path`**: All generated SQL uses fully-qualified `schema.table` names.
- **Session-scoped**: All `chat_service` writes are tagged with `session_id` (enforced in WHERE clauses).

---

## Changelog

### 2026-09-10 — Initial implementation
- Created full agent package: state, events, sql_executor, prompts, tools (orchestrator + worker), worker_graph, orchestrator_graph, entrypoint
- Added CheckpointerService (AsyncPostgresSaver with psycopg3 pool)
- Added ChatService (chats, chat_messages, artifacts CRUD)
- Updated ws_agent.py: ChatAgent routing, ask_user_response, resume, bug fix
- Updated main.py: checkpointer + chat table init at startup
- Added DATABASE_URL to config.py
- Added langgraph + langgraph-checkpoint-postgres + psycopg to requirements.txt
