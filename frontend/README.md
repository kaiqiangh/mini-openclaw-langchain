# Frontend

Next.js App Router frontend for Mini-OpenClaw.

## Route Map

| Route        | Purpose                                                 |
| ------------ | ------------------------------------------------------- |
| `/`          | Main workspace UI (agents/sessions + chat + inspector). |
| `/usage`     | Usage analytics, trend chart, CSV export.               |
| `/scheduler` | Cron + heartbeat control plane and run history.         |

## UI Model

- Desktop workspace: draggable split panes (`Sidebar | Chat | Inspector`) with localStorage persistence.
- Mobile workspace: tab-switched panels.
- Inspector modes:
  - workspace file editing
  - per-agent runtime config editing (`/api/config/runtime`)
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

- agent/sessions/chat/files/tokens/usage
- config: rag mode + runtime config
- scheduler: cron jobs, runs/failures, heartbeat config/runs

All agent-scoped calls append `agent_id`.

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Backend default target is `http://<host>:8002`.

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
