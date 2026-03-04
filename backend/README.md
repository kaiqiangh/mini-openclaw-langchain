# Backend

FastAPI backend for Mini-OpenClaw LangChain.

## Core Responsibilities

- Multi-agent runtime management (`AgentManager`).
- Chat execution (sync + SSE stream) with LangChain `create_agent`.
- Tool execution with policy gates and audit trails.
- Scheduler runtime (cron + heartbeat) with API control.
- Retrieval over memory/knowledge using SQLite-first indexes.
- Per-agent usage accounting.

## Canonical Tool Catalog

Aliases were removed in favor of one canonical name per capability.

- `terminal`, `python_repl`, `fetch_url`
- `read_files` (supports both `path` and `paths`)
- `read_pdf` (optional dependency: `requirements-pdf.txt`)
- `search_knowledge_base`, `web_search`
- `sessions_list`, `session_history`, `agents_list`
- `scheduler_cron_jobs`, `scheduler_cron_runs`
- `scheduler_heartbeat_status`, `scheduler_heartbeat_runs`
- `apply_patch`

## Service Graph

```mermaid
flowchart TB
  API["FastAPI /api/v1/*"] --> AM["AgentManager"]
  AM --> PROMPT["PromptBuilder"]
  AM --> TOOLS["ToolRunner + policy"]
  AM --> RETR["MemoryIndexer + knowledge tool"]
  RETR --> DB["storage/retrieval.db (SQLite/FTS5)"]
  AM --> SESS["SessionManager"]
  AM --> USAGE["UsageStore"]
  API --> SCH["CronScheduler + HeartbeatScheduler"]
```

## Agent Loop Architecture

The backend keeps one public orchestrator (`AgentManager`) and now separates
loop concerns into dedicated graph modules:

- `graph/retrieval_orchestrator.py`
- `graph/tool_orchestrator.py`
- `graph/usage_orchestrator.py`
- `graph/stream_orchestrator.py`
- `graph/agent_loop_types.py`

This separation is structural only; request/response and stream behavior are unchanged.

### Loop Module Responsibilities

| Module                      | Responsibility                                                                          | Side Effects                                                    |
| --------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `retrieval_orchestrator.py` | Decide whether RAG is active and build retrieval envelope (`results`, `rag_context`).   | None (pure orchestration around `MemoryIndexer`).               |
| `tool_orchestrator.py`      | Build policy-filtered LangChain tools and create loop agent (`create_agent`).           | Creates tool runner and may switch to tool-loop model override. |
| `stream_orchestrator.py`    | Token/reasoning extraction and incremental token diff logic for stream updates.         | None (pure content parsing helpers).                            |
| `usage_orchestrator.py`     | Normalize usage payloads, dedupe by source, compute signatures, and persist usage rows. | Writes to `UsageStore` when usage is finalized.                 |
| `agent_loop_types.py`       | Typed state containers for streaming and retrieval stages.                              | None.                                                           |

### Run-Once Loop (`AgentManager.run_once`)

1. **Resolve runtime and model profile**

- Load agent-effective runtime config (global + workspace config).
- Resolve active LLM profile and instantiate/reuse `ChatOpenAI`.

2. **Build retrieval envelope**

- `RetrievalOrchestrator.build_envelope(...)` checks `runtime.rag_mode`.
- If enabled, run memory retrieval through `MemoryIndexer.retrieve(...)`.
- Build transient request context in this exact format:
  - `"[Memory Retrieval Results]\n- (score) text ..."`

3. **Build prompt + message list**

- `PromptBuilder` assembles system prompt from workspace files.
- Conversation history is converted into LangChain messages.
- Retrieval context (if any) is appended as a system message.

4. **Build tool-enabled agent**

- `ToolOrchestrator.build_agent(...)` wires:
  - available mini tools
  - explicit trigger allowlist (`chat`, `cron`, `heartbeat`)
  - tool runner with retry-guard
  - LangChain structured tools
- Tool-loop model override logic is preserved (`TOOL_LOOP_MODEL*`).

5. **Execute agent**

- Invoke with recursion limit and callbacks.
- Callback stack includes internal audit + usage capture + optional tracing callbacks.

6. **Aggregate and persist usage**

- `UsageOrchestrator` normalizes callback usage payloads, dedupes repeated message IDs,
  computes prices, and writes `UsageStore` records.
- Response payload is unchanged (`text` or `structured_response` + `messages` + `usage`).

### Streaming Loop (`AgentManager.astream`)

The stream path follows the same build stages and then emits SSE-aligned events:

- `run_start`
- `agent_update`
- `retrieval` (when RAG is enabled)
- `tool_start`
- `tool_end`
- `reasoning`
- `token`
- `new_response`
- `usage`
- `done`
- `error`

`stream_orchestrator` utilities preserve token extraction, incremental diffing, and
reasoning extraction logic so event ordering/content remains stable.

`StreamLoopState` keeps stream-only mutable state isolated from orchestration steps:

- `pending_new_response`: flips true when a tool result finishes and a new model segment should begin.
- `final_tokens`: linear token buffer used to assemble final `done.content`.
- `fallback_final_text`: model-update fallback when message token stream is absent.
- `token_source`: tracks `messages` vs `updates` for deterministic stream metadata.
- `latest_model_snapshot`: previous update snapshot for incremental token diff.
- `emitted_reasoning`: dedupe set for reasoning snippets.
- `emitted_agent_update`: ensures at least one model progress event is emitted.

### Tool Calling Flow

1. Agent chooses tool call in the model node.
2. Tool call is routed through `ToolRunner`.
3. Policy checks and retry-guard are enforced before execution.
4. Tool outputs are emitted into stream events and fed back into the agent loop.
5. Audit callbacks capture tool start/end and associate them with `run_id`/`session_id`.

### Memory, Embeddings, and Retrieval Flow

`MemoryIndexer` handles retrieval for `memory/MEMORY.md`:

1. Resolve retrieval runtime settings (`top_k`, chunking, blend weights).
2. Resolve storage engine:

- SQLite (default) with FTS prefilter and vector similarity.
- JSON fallback maintained for compatibility/migration safety.

3. Generate query embedding (if embedding credentials/provider are available).
4. Retrieve chunks and blend lexical + semantic scores.
5. Return ranked retrieval rows consumed by the agent loop.

Embedding behavior:

- Provider/model come from runtime/global config and environment keys.
- If embedding calls fail, query embedding becomes empty and retrieval continues with
  lexical scoring (no agent-loop crash).

### Observability and Accounting

- `AuditCallbackHandler`: run/step/tool/message-link audit files.
- `UsageCaptureCallbackHandler`: captures per-call model usage payloads.
- `UsageOrchestrator`: dedupe + normalize + compute cost + persist usage row.
- Optional external tracing callbacks are attached when tracing is enabled.

### Behavior-Parity Guarantee for This Refactor

This architecture cleanup does not change:

- API contracts or route shapes.
- Chat/session persistence behavior.
- SSE event names/order semantics.
- Tool gating and policy enforcement points.
- Usage normalization and pricing semantics.

## Runtime Config Matrix

| Path                                          | Purpose                                     |
| --------------------------------------------- | ------------------------------------------- |
| `runtime.retrieval.storage.engine`            | `sqlite` (default) or fallback `json`.      |
| `runtime.retrieval.storage.db_path`           | Relative DB path per agent workspace.       |
| `runtime.retrieval.storage.fts_prefilter_k`   | Candidate count before semantic scoring.    |
| `runtime.tool_network.allow_http_schemes`     | Allowed URL schemes for fetch tools.        |
| `runtime.tool_network.block_private_networks` | Block localhost/private/link-local targets. |
| `runtime.tool_network.max_redirects`          | Redirect safety cap.                        |
| `runtime.tool_network.max_content_bytes`      | Maximum fetched response size.              |
| `runtime.chat_enabled_tools`                  | Explicit chat-trigger high-risk tools.      |
| `runtime.tool_execution.terminal.*`           | Terminal sandbox, allowlist, and limits.    |
| `runtime.scheduler.api_enabled`               | Enable/disable scheduler API routes.        |
| `runtime.scheduler.runs_query_default_limit`  | Default limit for runs/failures queries.    |
| `runtime.heartbeat.*`                         | Heartbeat schedule + execution window.      |
| `runtime.cron.*`                              | Cron polling, retry/backoff, retention.     |
| `runtime.llm_runtime.profile`                 | Active LLM profile name override.           |

## LLM Profiles

- Provider resolution is profile-driven (`llm_profiles` + `default_llm_profile`).
- Driver model is `openai_compatible` for OpenAI-compatible providers.
- Azure AI Foundry is supported through the `azure_foundry` profile template.
- Usage accounting prefers explicit profile provider IDs.

## LLM Model Selection (Tool Loop)

- Tool-enabled loops can be overridden with:
  - `TOOL_LOOP_MODEL` (global override for all configured models).
  - `TOOL_LOOP_MODEL_OVERRIDES` (per-model mapping).
- `TOOL_LOOP_MODEL_OVERRIDES` supports:
  - JSON object format (preferred): `{"source-model": "tool-model"}`
  - comma-separated key/value format: `source-model=tool-model,source2=tool2`
- If no override applies, the configured model is used as-is.

## API Reference

### Chat / Sessions / Agents

- `POST /api/v1/agents/{agent_id}/chat`
- `GET|POST /api/v1/agents/{agent_id}/sessions`
- `PUT|DELETE /api/v1/agents/{agent_id}/sessions/{session_id}`
- `POST /api/v1/agents/{agent_id}/sessions/{session_id}/archive`
- `POST /api/v1/agents/{agent_id}/sessions/{session_id}/restore`
- `GET|POST|DELETE /api/v1/agents`
- `POST /api/v1/agents/bulk-delete`
- `POST /api/v1/agents/bulk-export`
- `POST /api/v1/agents/bulk-runtime-patch`
- `GET /api/v1/agents/templates`
- `GET /api/v1/agents/templates/{template_name}`
- `GET /api/v1/agents/{agent_id}/runtime-diff`

### Files / Tokens / Usage

- `GET|POST /api/v1/agents/{agent_id}/files`
- `GET /api/v1/agents/{agent_id}/files/index`
- `GET /api/v1/skills`
- `GET /api/v1/agents/{agent_id}/tokens/session/{session_id}`
- `POST /api/v1/agents/{agent_id}/tokens/files`
- `GET /api/v1/agents/{agent_id}/usage/summary`
- `GET /api/v1/agents/{agent_id}/usage/records`

### Config

- `GET|PUT /api/v1/agents/{agent_id}/config/rag-mode`
- `GET|PUT /api/v1/agents/{agent_id}/config/runtime` (validated, atomic write)
- `GET|PUT /api/v1/config/tracing` (persisted in `storage/runtime_state.json`)

### Scheduler

- `GET|POST /api/v1/agents/{agent_id}/scheduler/cron/jobs`
- `PUT|DELETE /api/v1/agents/{agent_id}/scheduler/cron/jobs/{job_id}`
- `POST /api/v1/agents/{agent_id}/scheduler/cron/jobs/{job_id}/run`
- `GET /api/v1/agents/{agent_id}/scheduler/cron/runs`
- `GET /api/v1/agents/{agent_id}/scheduler/cron/failures`
- `GET|PUT /api/v1/agents/{agent_id}/scheduler/heartbeat`
- `GET /api/v1/agents/{agent_id}/scheduler/heartbeat/runs`
- `GET /api/v1/agents/{agent_id}/scheduler/metrics`
- `GET /api/v1/agents/{agent_id}/scheduler/metrics/timeseries`

## Threat Model (Current)

- Workspace path escape prevention in file tools/endpoints.
- URL fetch restrictions (scheme, host policy, content bounds, redirect cap).
- Terminal command allowlist + process sandbox backend + environment secret scrubbing.
- Autonomous tool calls blocked unless explicitly allowlisted.
- API middleware:
  - admin bearer token gate (`APP_ADMIN_TOKEN`)
  - trusted hosts
  - CORS restrictions
  - rate limiting
  - baseline hardening headers

Known limitations:

- Sandbox guarantees are host-local and depend on available OS sandbox backend.
- In `hybrid_auto` mode without a compatible backend, terminal execution is denied unless explicitly set to `unsafe_none`.

## Retrieval Notes

- Default engine: SQLite (`storage/retrieval.db`) per agent.
- `index_meta` stores digest + schema version.
- `chunks_fts` provides lexical prefilter.
- Semantic + lexical blending is preserved from previous scoring.
- Legacy JSON index is imported on first SQLite use, and JSON read fallback remains available.

## Operations

- Scheduler run/failure logs are JSONL in each workspace `storage/`.
- Cron and heartbeat records now include `started_at_ms`, `finished_at_ms`, `duration_ms`, and schedule lag where applicable.
- Metrics endpoints aggregate these records into windowed percentiles (`p50/p90/p99`) and bucketed trends.
- Heartbeat skip states include `skipped_no_prompt` for empty/comment-only prompts.
- Cron and heartbeat write paths are lock-protected.

## Local Run

```bash
cd backend
uv venv --python=python3.13.7
uv pip install -r requirements.txt
# Optional PDF tool support:
# uv pip install -r requirements-pdf.txt
cp .env.example .env
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Minimum required env:

- `APP_ADMIN_TOKEN`
- one API key for the active LLM profile (for example `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, or `AZURE_FOUNDRY_API_KEY`)

Health check:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

## Tests

```bash
cd backend
./.venv/bin/pytest -q
```
