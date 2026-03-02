# Mini-OpenClaw LangChain

[![Build](https://img.shields.io/badge/build-passing-15803d)](#testing) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![Version](https://img.shields.io/badge/version-0.1.0-blue) [![Python](https://img.shields.io/badge/python-3.13+-1d4ed8)](#quickstart) [![Next.js](https://img.shields.io/badge/next.js-15-black)](#architecture) ![LangChain](https://img.shields.io/badge/LangChain-1.2.10-15803d)

Reliability-first, local-first agent workspace inspired by OpenClaw patterns with minimal overhead on top of LangChain:

- Multi-agent isolated workspaces.
- Safer tool/network controls (`fetch_url`, `web_search`, terminal env scrubbing).
- Scheduler API + UI (`/scheduler`) for cron and heartbeat operations.
- SQLite-first retrieval index with FTS prefilter and JSON migration fallback.
- Streaming chat with retrieval/tool traces and markdown rendering.

## Architecture

```mermaid
flowchart LR
  U["Operator"] --> FE["Frontend (Next.js)"]
  FE --> API["FastAPI API"]
  API --> AM["AgentManager (LangChain create_agent)"]
  AM --> WS["workspaces/<agent_id>/"]
  WS --> CFG["config.json (effective runtime)"]
  WS --> MEM["memory/MEMORY.md"]
  WS --> KNOW["knowledge/*"]
  WS --> STORE["storage/retrieval.db, usage, audits"]
  API --> SCH["Scheduler (cron + heartbeat)"]
  AM --> TOOLS["ToolRunner + policy gates"]
  AM --> LLM["Provider profiles (OpenAI-compatible/Azure Foundry)"]
  AM --> EMB["Embeddings (OpenAI-compatible/Google)"]
```

## Feature Matrix

| Area                   | Status | Notes                                                                                 |
| ---------------------- | ------ | ------------------------------------------------------------------------------------- |
| Multi-agent workspaces | Ready  | Per-agent sessions, memory, knowledge, usage, scheduler state.                        |
| Chat + streaming       | Ready  | SSE streaming, debug events, tool/retrieval traces.                                   |
| Tool hardening         | Ready  | URL scheme/host controls, private network blocking, env scrubbing.                    |
| Scheduler API          | Ready  | Cron CRUD, run-now, runs/failures, heartbeat config/runs.                             |
| Scheduler UI           | Ready  | `/scheduler` page for cron + heartbeat controls and history.                          |
| Retrieval engine       | Ready  | SQLite + FTS5 prefilter, semantic+lexical blending, legacy JSON migration.            |
| Runtime config editor  | Ready  | Agent-scoped JSON editor in Inspector via `/api/v1/agents/{agent_id}/config/runtime`. |
| Usage analytics        | Ready  | Model breakdown, trend chart, CSV export.                                             |

## Security Model

- `/api/v1/*` routes are protected by `Authorization: Bearer <APP_ADMIN_TOKEN>` (except health/readiness).
- File APIs are workspace-root scoped and path-guarded.
- Tool policy gates autonomous triggers (`heartbeat`, `cron`) with explicit allowlists.
- `fetch_url` defaults:
  - allowed schemes: `http`, `https`
  - private/loopback/link-local blocking enabled
  - redirect cap + content-size cap
- Terminal tool executes with sanitized environment (secret-like vars stripped).
- CORS + trusted hosts + rate limit middleware enabled by default.

## Quickstart

### 1) Backend

```bash
cd backend
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
uv run --python .venv/bin/python uvicorn app:app --host 127.0.0.1 --port 8000
```

Set at least:

- `APP_ADMIN_TOKEN`
- one key for your active `DEFAULT_LLM_PROFILE` (for example `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, or `AZURE_FOUNDRY_API_KEY`)

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Optional (recommended for local auth): set `NEXT_PUBLIC_APP_ADMIN_TOKEN` in `frontend/.env.local`.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) when using `./oml start` (backend single-origin proxy enabled).
Direct frontend dev server remains available at [http://localhost:3000](http://localhost:3000).

## Repo-local CLI (`./oml`)

`oml` is a repo-local command (`./oml`) for running and operating Mini-OpenClaw locally without requiring global installation. It manages both backend and frontend execution, handles logs and PIDs, and runs health checks.

### Requirements

- `bash`
- `uv`
- `node` + `npm`
- `curl`

### Quick Start

```bash
./oml help
./oml start
./oml status
./oml logs --follow
./oml stop
```

When started via `./oml start`, the backend runs with the frontend proxy enabled, allowing you to access the app directly at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Core Commands

- **`start [target]`**: Starts services (`all`, `backend`, or `frontend`) in detached mode. It writes PID files to `.oml/run/`, logs to `.oml/log/`, and waits for health checks to pass. Idempotent if already running.
- **`stop [target]`**: Stops managed services safely. Uses graceful SIGTERM first, with a SIGKILL fallback. Refuses to kill unmanaged PIDs.
- **`restart [target]`**: Equivalent to `stop` followed by `start`.
- **`status`**: Prints service-level status including state (`running`/`stopped`), PID, health (`ok`, `degraded`, `down`), and service URL.
- **`logs [target]`**: Shows logs from `.oml/log`. Supports `--follow` and `--lines N`.
- **`update`**: Safely syncs local dependencies (`uv` for Python, `npm ci` for Node) without mutating git history.
- **`doctor`**: Validates prerequisites, checks `backend/.env`, and detects port conflicts.
- **`ports`**: Prints effective URL/ports used by the runtime config.
- **`version` / `help`**: Prints component versions and CLI usage.

### Runtime State & Configuration

The CLI stores its runtime state in `.oml/run/` and `.oml/log/`.

You can override defaults by creating an `.oml/config.env` file (or by exporting environment variables):

```bash
OML_BACKEND_HOST=127.0.0.1
OML_BACKEND_PORT=8000
OML_FRONTEND_HOST=127.0.0.1
OML_FRONTEND_PORT=3000
OML_HEALTH_TIMEOUT_SECONDS=30
```

### Exit Codes

- `0`: Success | `1`: Invalid command/argument | `2`: Missing binary
- `3`: Health/start timeout | `4`: Unsafe stop or runtime failure
- `5`: Update failure | `6`: Doctor critical failure

### Troubleshooting

- **Start fails with timeout**: Check `.oml/log/*.log`. Ensure `backend/.env` is correctly configured and `frontend/node_modules` exists.
- **Stop refuses to kill PID**: The PID file doesn't match an expected managed process. Run `rm -f .oml/run/*.pid` to clear stale PIDs, then retry.

## Testing

### Backend

```bash
cd backend
./.venv/bin/pytest -q
```

### Frontend

```bash
cd frontend
npm run test:run
npm run build
```

## Repository Layout

- `backend/`: FastAPI APIs, AgentManager, tools, scheduler, retrieval.
- `frontend/`: Next.js app router UI, API client, app store, scheduler/usage/workspace pages.

## Roadmap (Near-term)

- Add stronger process-level sandboxing for terminal execution (beyond env scrubbing).
- Expand scheduler observability (job duration/latency aggregates).
- Add richer agent management UX (bulk actions, templates, diffable runtime config).
