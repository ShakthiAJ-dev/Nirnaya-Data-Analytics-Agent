# Nirnaya — AI-Powered Data Analytics Agent

## Project overview

SaaS analytics platform. Users upload datasets (CSV/Parquet/Excel), an LLM agent generates metadata and answers questions via SQL (Trino → Postgres). No login required — all session-based (anonymous, HMAC-signed tokens stored in Redis).

Stack: FastAPI + Supabase (Postgres + Storage) + Upstash Redis + AWS Bedrock (Anthropic Haiku) + LangChain.

---

## Monorepo structure

```
Nirnaya-Data-Analytics-Agent/
├── BE_Nirnaya/        FastAPI backend
└── FE_Nirnaya/        Frontend (Vercel deploy)
```

---

## BE_Nirnaya — Backend

### Entry point
`app/main.py` — FastAPI lifespan: starts Supabase → Redis → WSManager → calls `DatabaseService.initialize_app_tables()`.

### Key services (`app/services/`)

| Service | Purpose |
|---|---|
| `SupabaseService` | Wraps supabase-py v2. Two clients: `anon` (RLS) and `admin` (service role). |
| `RedisService` | Upstash TLS. Cache, rate-limit, session blobs. |
| `SessionService` | HMAC-SHA256 tokens. AES-256-GCM encrypted API key storage. |
| `LLMService` | Per-session LangChain factory. Bedrock / Anthropic / OpenAI. |
| `ProjectService` | CRUD for `public.projects` table (= chat sessions). |
| `DatabaseService` | Full database lifecycle: create schema, upload files, generate metadata, business rules, delete table. |
| `DataService` | Facade: `TableService` (session-partitioned PostgREST CRUD) + `FileService` (Supabase Storage). |

### Supabase RPC functions required (run once in SQL editor)

```sql
-- DDL executor (schema creation, table creation, INSERT)
CREATE OR REPLACE FUNCTION exec_ddl(sql text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
AS $$ BEGIN EXECUTE sql; END; $$;

-- SELECT query executor (returns JSON array)
CREATE OR REPLACE FUNCTION exec_query(sql text)
RETURNS json LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE result json;
BEGIN
  EXECUTE format('SELECT json_agg(t) FROM (%s) t', sql) INTO result;
  RETURN COALESCE(result, '[]'::json);
END;
$$;
```

`exec_query` is auto-created at startup via `initialize_app_tables` if `exec_ddl` exists.

### Public schema app tables (auto-created at startup)

- `public.projects` — chat sessions. Fields: `id UUID, session_id, title (default "Untitled"), database_id UUID, created_at, updated_at`
- `public.databases` — user databases. Fields: `id UUID, session_id, name, schema_name (unique), is_demo bool, metadata_path, created_at`
- `public.file_uploads` — uploaded file records per table. Fields: `id UUID, session_id, database_id UUID, filename, original_filename, table_name, row_count, status, created_at`

### User database schema naming

Format: `n_{first 12 hex chars of session_id}_{sanitized_db_name}` (max 63 chars).

Data tables live inside that schema. `_row_id BIGINT GENERATED ALWAYS AS IDENTITY` is added as PK to every ingested table.

### Metadata JSON structure (stored in `nirnaya-sessions` bucket at `{session_id}/metadata/{database_id}.json`)

```json
{
  "database_name": "...",
  "schema_name": "n_abc123_mydb",
  "generated_at": "ISO timestamp",
  "generated_by": "nirnaya-llm | nirnaya-stats-fallback",
  "business_rules": [
    {"_id": "BR_1_abc123", "title": "Rule title", "content": "Rule content"}
  ],
  "tables": {
    "table_name": {
      "overview": "...",
      "use_case": "...",
      "grain": "One row represents one ...",
      "domain_tags": ["finance", "sales"],
      "key_columns": ["id", "date", "amount"],
      "currency": "USD or null",
      "timezone": "UTC or null",
      "tenant_column": "col_name or null",
      "key_notes": "Important caveats...",
      "pii_columns": ["email", "name"],
      "row_count": 412,
      "column_count": 9,
      "columns": [
        {
          "name": "invoice_id",
          "data_type": "bigint",
          "type_class": "numeric",
          "nullable": true,
          "min": 1.0,
          "max": 412.0,
          "avg": 206.5,
          "null_count": 0,
          "unique_values_count": 412
        },
        {
          "name": "billing_country",
          "data_type": "text",
          "type_class": "text",
          "nullable": true,
          "null_count": 0,
          "unique_values_count": 24,
          "unique_values": ["Argentina", "Australia", ...]
        }
      ],
      "sample_rows": [...]
    }
  }
}
```

Column `type_class` values: `numeric`, `datetime`, `boolean`, `text`, `uuid`, `json`, `array`, `binary`, `enum`.
Text columns with `unique_values_count < 50` include a `unique_values` list.

Business rules: FE sends complete list on each update (PUT replaces entirely).

### API routes

All routes under `/api/v1`. All (except `/session/init` and `/health`) require `Authorization: Bearer <token>`.

**Session**
- `POST /session/init` — create anonymous session, returns token
- `POST /session/llm-provider-key` — store encrypted LLM API key
- `GET /session/models` — available models

**Projects**
- `POST /projects` — create project (title = "Untitled", optional database_id)
- `GET /projects` — list session projects
- `GET /projects/{id}` — single project
- `PATCH /projects/{id}/title` — update title (call on first user message)
- `DELETE /projects/{id}` — delete project

**Databases**
- `POST /databases` — create database (creates Postgres schema)
- `GET /databases` — list databases **with embedded metadata** (metadata key on each db object)
- `GET /databases/{id}` — single database
- `DELETE /databases/{id}` — delete (blocked for `is_demo=true`)
- `POST /databases/{id}/upload` — upload CSV/Parquet/Excel; table name conflict → 422; appends new tables to existing metadata
- `DELETE /databases/{id}/tables/{table_name}` — drop table from schema + remove from metadata
- `GET /databases/{id}/metadata` — get raw metadata JSON
- `PUT /databases/{id}/business-rules` — replace business rules `{rules: [...]}`
- `DELETE /session/cleanup` — delete all session data (databases, projects, files)

**WebSocket**
- `WS /ws/agent` — LLM agent. Auth frame first, then message loop.

### File upload behaviour

1. Parse file (pandas): CSV → 1 table, Parquet → 1 table, Excel → 1 table per sheet
2. Check table name conflicts against existing schema tables → 422 if conflict
3. Ingest via `exec_ddl` INSERT batches (200 rows/batch)
4. Query Postgres for column stats (min/max/avg for numeric, unique values for text <50 distinct)
5. Call Bedrock Haiku for semantic enrichment (overview, use_case, grain, domain_tags, key_columns, currency, timezone, tenant_column, key_notes, pii_columns)
6. Merge LLM result with factual stats; APPEND to existing metadata (preserve other tables + business_rules)
7. Store at `{session_id}/metadata/{database_id}.json` in `nirnaya-sessions` bucket

### Demo database

Pre-existing Music E-commerce schema (`demo`) with 11 tables: invoice, invoice_line, playlist, album, playlist_track, artist, customer, employee, genre, media_type, track. Metadata in `BE_Nirnaya/dema_metadata.json`. Demo databases have `is_demo=true` — cannot be deleted.

### LLM setup

Default: AWS Bedrock via `ChatBedrockConverse`. Model: `global.anthropic.claude-haiku-4-5-20251001-v1:0` (cross-region inference profile). Region: `us-east-1`. Configured in `.env` as `BEDROCK_API_KEY`, `BEDROCK_ANTHROPIC_MODEL`, `BEDROCK_REGION`.

Users can also provide their own Anthropic or OpenAI key (stored encrypted in Redis for session duration).

### Known bugs in existing code (do not reintroduce)

- `settings.bedrock_endpoint` does not exist in `config.py` — `llm_service.py` will `AttributeError` on Bedrock path.
- `ws_agent.py` has malformed `elif request_type == "":` block.
- `file_service.py` `list_files` references `auto_ensure` before it's defined.

### Environment variables (`.env`)

```
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
REDIS_URL  (rediss://... Upstash TLS)
SESSION_SECRET, KEY_ENCRYPTION_SECRET
SESSION_TTL=7200
CLAUDE_PROVIDER=bedrock
BEDROCK_API_KEY, BEDROCK_ANTHROPIC_MODEL, BEDROCK_REGION=us-east-1
CORS_ORIGINS / ALLOWED_ORIGINS
```

### Dependencies (requirements.txt)

FastAPI, uvicorn, pydantic-settings, supabase>=2.10, redis[hiredis], openai, anthropic, boto3, botocore, structlog, cryptography, langchain-core/openai/anthropic/aws, httpx, **pandas>=2.0, openpyxl>=3.1, pyarrow>=14.0, python-multipart>=0.0.9**

---

## Development notes

- Caveman mode active by default in this project (startup hook).
- Git user: Dev-Shakthi, main branch.
- FE deployed on Vercel. BE on Render (assumed).
- Session is anonymous — no user accounts. All data scoped by `session_id`.
- `_require_session` helper duplicated in `projects.py` and `databases.py` — consider extracting to `dependencies.py` in future.
