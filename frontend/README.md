# Mini-OpenClaw Frontend

Next.js App Router frontend for Mini-OpenClaw.

## What It Provides

- Multi-agent workspace management (switch/create/delete agent workspaces).
- Agent-scoped session list with active/archive/restore/delete.
- Streaming chat UI with tool/reasoning/usage debug traces.
- Inspector with Monaco editor for workspace files.
- Usage analytics page (`/usage`) with token + cost breakdown.

## Architecture

```text
frontend/src/
  app/
    layout.tsx            # app root + provider
    page.tsx              # main tri-panel workspace UI
    usage/page.tsx        # usage analytics page
    globals.css           # visual system
  lib/
    api.ts                # typed API client (agent-aware)
    store.tsx             # global state + stream orchestration
  components/
    layout/               # Navbar, Sidebar, ResizeHandle
    chat/                 # Chat panels + debug rendering
    editor/               # InspectorPanel (Monaco)
```

## UX Model

- Desktop: `Agents/Sessions | Chat | Inspector` panels.
- Mobile: tab-switched panel layout.
- Agent switch updates:
  - sessions,
  - message history,
  - inspected workspace files (`memory/`, `workspace/`, `knowledge/`).

## Requirements

- Node.js 18+ (Node 22 LTS recommended)
- npm

## Quick Start

```bash
cd frontend
npm install
npm run dev
```

Open: `http://localhost:3000`

Backend is expected at: `http://<current-host>:8002`.

## Build

```bash
cd frontend
npm run build
npm run start
```

## Backend Integration

The frontend calls:

- `/api/agents`
- `/api/sessions*` (with `agent_id`)
- `/api/chat` (body `agent_id`)
- `/api/files` (with `agent_id`)
- `/api/usage/*` (with `agent_id`)
- `/api/config/rag-mode`
- `/api/tokens/*`

## Notes

- Monaco editor is dynamically imported (`ssr: false`).
- SSE parsing is custom and supports segmented events.
- Usage page shows explicit token counters:
  - input,
  - cached input,
  - uncached input,
  - output,
  - reasoning,
  - total,
  - estimated USD.
