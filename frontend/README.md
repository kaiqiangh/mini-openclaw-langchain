# Frontend

Next.js App Router frontend for Mini-OpenClaw.

## Route Map

| Route        | Purpose                                                                    |
| ------------ | -------------------------------------------------------------------------- |
| `/`          | Main workspace UI (agents/sessions + chat + inspector).                    |
| `/usage`     | Usage analytics, trend chart, CSV export.                                  |
| `/scheduler` | Cron + heartbeat control plane, observability aggregates, and run history. |

## UI Model

- Desktop workspace: draggable split panes (`Sidebar | Chat | Inspector`) with localStorage persistence.
- Mobile workspace: tab-switched panels.
- Inspector modes:
  - workspace file editing
  - per-agent runtime config editing (`/api/v1/agents/{agent_id}/config/runtime`)
  - template loading, runtime diff views, and bulk runtime patch actions
- Agent management:
  - single create/delete + switch
  - bulk export/delete actions
- Chat rendering:
  - markdown + GFM
  - sanitization
  - fenced code copy action
  - retrieval + tool debug cards

## State Model (`src/lib/store.tsx`)

- Global app context (`AppProvider`) tracks:
  - `currentAgentId`
  - sessions + current session
  - chat message stream state
  - inspector file state
  - RAG toggle state (agent-scoped)
- Agent switch performs:
  1. load rag mode for selected agent
  2. load sessions/history
  3. load default inspected file (`memory/MEMORY.md`)

## Streaming Event Model

`streamChat()` parses SSE payloads and forwards typed events to store reducer logic:

- `token`
- `retrieval`
- `tool_start`
- `tool_end`
- `reasoning`
- `usage`
- `done`
- `title`

The UI accumulates assistant tokens incrementally while preserving run debug traces.

## API Integration

`src/lib/api.ts` includes typed wrappers for:

- agent/sessions/chat/files/tokens/usage/compress
- config: rag mode + runtime config + runtime diff
- scheduler: cron jobs, runs/failures, heartbeat config/runs + metrics/timeseries
- agent management: bulk delete/export/runtime patch and template discovery

All agent-scoped calls append `agent_id`, and all API calls target `/api/v1/*`.
Auth token source order:

- `NEXT_PUBLIC_APP_ADMIN_TOKEN`
- `localStorage["mini-openclaw:admin-token"]`

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

API client default is relative (`/api/v1/*`), so no hardcoded backend host/port is required.

Manual development modes:

- `./oml start`: browser origin is `http://127.0.0.1:8000`; backend proxies frontend pages and API stays same-origin.
- `npm run dev` with backend on `127.0.0.1:8000`: Next.js rewrites `/api/v1/*` to the backend automatically.

Optional frontend envs:

- `NEXT_DEV_API_PROXY_URL`: overrides the manual-dev rewrite target (default `http://127.0.0.1:8000`)
- `NEXT_PUBLIC_API_BASE_URL`: advanced absolute API override
- `NEXT_PUBLIC_APP_ADMIN_TOKEN`: optional default bearer token for local auth

## Test + Build Flow

```bash
cd frontend
npm run test:run
npm run build
```

Current tests cover:

- SSE parsing
- store agent/file flows
- chat rendering (retrieval/tool cards + markdown sanitization)
- API agent scoping for rag mode
- scheduler metrics and agent bulk/template API routes
