---
goal: Frontend Operator Console Implementation Plan
version: 1.0
date_created: 2026-03-06
last_updated: 2026-03-06
owner: Codex
status: Planned
tags: [feature, frontend, architecture, observability, workflow]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This plan defines the implementation steps for evolving the frontend into a hybrid operator console with dedicated `Workspace`, `Sessions`, `Runs`, and `Trace Explorer` workflows. The plan preserves the current live workspace while moving investigation and observability tasks into route-based views with URL-addressable state.

## 1. Requirements & Constraints

- **REQ-001**: Preserve the existing live workspace route at `frontend/src/app/page.tsx` as the primary active execution surface.
- **REQ-002**: Add dedicated operator routes for `/sessions`, `/runs`, and `/traces` under the Next.js App Router.
- **REQ-003**: Replace ad hoc per-page navigation with a shared operator shell rendered from a route-level layout.
- **REQ-004**: Encode review-oriented page state in the URL, including selected records, filter values, and detail-drawer state.
- **REQ-005**: Keep live streaming chat state in `frontend/src/lib/store.tsx` until route-based workspace refactoring is necessary.
- **REQ-006**: Implement a reusable route-aware detail drawer for session, run, and trace detail.
- **REQ-007**: Implement keyboard-operable splitters for the workspace layout.
- **REQ-008**: Fix chat auto-scroll so it only sticks to the bottom while the user remains near the live edge.
- **REQ-009**: Keep existing `Usage` and `Scheduler` routes functional during the migration.
- **REQ-010**: Reuse existing backend APIs for sessions, usage, and scheduler data before introducing new frontend-only abstractions.
- **SEC-001**: Preserve the current authenticated request flow in `frontend/src/lib/api.ts` and avoid bypassing the admin-session bootstrap path.
- **OBS-001**: Use `agent_id`, `session_id`, `run_id`, and `trigger_type` as first-class correlation identifiers across views.
- **OBS-002**: Do not ship the `Trace Explorer` UI without a persisted trace/read API or an explicit degraded empty-state contract.
- **CON-001**: The repository currently lacks dedicated trace-explorer APIs; the plan must treat that work as a dependency rather than assuming it already exists.
- **CON-002**: The repository currently lacks a `docs/` structure and a `plan/` structure; the implementation must create and use those directories consistently.
- **GUD-001**: Follow the Vercel Web Interface Guidelines for navigation clarity, keyboard access, and URL-addressable UI state.
- **GUD-002**: Use the existing UI primitive patterns in `frontend/src/components/ui/primitives.tsx` where possible instead of creating incompatible control variants.
- **PAT-001**: Split route containers, URL-state hooks, and presentational components so data-fetching logic does not remain embedded in page render code.
- **PAT-002**: Prefer route-group layouts in the Next.js App Router over repeating the navigation shell in every page component.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Establish the shared operator shell, route structure, and URL-state primitives without breaking the current workspace flow.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Create `frontend/src/app/(console)/layout.tsx` and move the shared navigation shell into the route group so `/`, `/usage`, `/scheduler`, `/sessions`, `/runs`, and `/traces` render inside one operator layout. |  |  |
| TASK-002 | Create `frontend/src/components/layout/AppShell.tsx` to replace the current `Navbar`-only pattern with primary navigation links for `Workspace`, `Sessions`, `Runs`, `Trace Explorer`, `Scheduler`, and `Usage`, plus current-agent and run-status context. |  |  |
| TASK-003 | Refactor `frontend/src/components/layout/Navbar.tsx` into shell subcomponents or remove it after `AppShell` is adopted by the route-group layout. Update `frontend/src/app/page.tsx`, `frontend/src/app/usage/page.tsx`, and `frontend/src/app/scheduler/page.tsx` to stop rendering page-local nav bars. |  |  |
| TASK-004 | Create `frontend/src/lib/url-state.ts` with shared helpers for reading and updating `URLSearchParams` via `usePathname`, `useRouter`, and `useSearchParams`. Expose deterministic helpers for string, enum, and boolean search params. |  |  |
| TASK-005 | Create `frontend/src/components/layout/DetailDrawer.tsx` with keyboard-dismiss, focus management, and route-driven open state. Use this component as the only drawer pattern for future session, run, and trace detail. |  |  |
| TASK-006 | Add route stubs for `frontend/src/app/sessions/page.tsx`, `frontend/src/app/runs/page.tsx`, and `frontend/src/app/traces/page.tsx` using the shared shell and empty-state placeholders until each route is populated. |  |  |

### Implementation Phase 2

- GOAL-002: Improve the workspace page so active operation stays fast while historical review moves into dedicated routes.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-007 | Update `frontend/src/components/layout/ResizeHandle.tsx` to support keyboard resizing semantics. Add `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, and arrow-key handling, or replace the button with a separator-like interactive control that is keyboard-operable. |  |  |
| TASK-008 | Update `frontend/src/app/page.tsx` to support keyboard-driven panel resizing and to preserve the current local-storage layout persistence behavior. |  |  |
| TASK-009 | Update `frontend/src/components/chat/ChatPanel.tsx` so auto-scroll runs only when the user is near the bottom of the message list. Add a stable threshold check and a "jump to latest" affordance when the user is reading older messages. |  |  |
| TASK-010 | Move mobile-panel selection in `frontend/src/app/page.tsx` from local-only state to URL-backed state so mobile workspace tabs are linkable and restore correctly. |  |  |
| TASK-011 | Add a `TracePreviewRail` component under `frontend/src/components/chat/` or `frontend/src/components/workspace/` that summarizes the latest tool calls, retrievals, and debug events for the active session without replacing the future `/traces` route. |  |  |

### Implementation Phase 3

- GOAL-003: Build the `Sessions` route as the primary entry point for navigating history and reviewing agent output.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-012 | Create `frontend/src/components/sessions/SessionsFilterBar.tsx` with agent, scope, search, and sort controls backed by URL state. |  |  |
| TASK-013 | Create `frontend/src/components/sessions/SessionsList.tsx` to render dense desktop rows and mobile cards from `getSessions(...)` results retrieved via `frontend/src/lib/api.ts`. |  |  |
| TASK-014 | Create `frontend/src/components/sessions/SessionDetail.tsx` to load `getSessionHistory(...)`, render transcript data, and summarize related tool-call counts already persisted in session history. |  |  |
| TASK-015 | Implement `frontend/src/app/sessions/page.tsx` as a container route that reads URL state, fetches session lists and session history, and opens the selected session inside `DetailDrawer`. |  |  |
| TASK-016 | Refactor `frontend/src/components/layout/Sidebar.tsx` so the sidebar remains focused on quick actions for the workspace rather than acting as the primary session-browser surface. |  |  |

### Implementation Phase 4

- GOAL-004: Build the `Runs` route and decouple operational review from the current Usage and Scheduler pages.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-017 | Create `frontend/src/lib/runs-model.ts` to normalize data from `getUsageRecords(...)`, `listCronRuns(...)`, `listCronFailures(...)`, and `listHeartbeatRuns(...)` into a single frontend run view model containing `agent_id`, `session_id`, `run_id`, `trigger_type`, status, timestamp, and duration/latency fields when available. |  |  |
| TASK-018 | Create `frontend/src/components/runs/RunsFilterBar.tsx`, `frontend/src/components/runs/RunsTable.tsx`, and `frontend/src/components/runs/RunDetail.tsx` using URL-backed filters and the shared `DetailDrawer`. |  |  |
| TASK-019 | Implement `frontend/src/app/runs/page.tsx` as the route container that fetches and merges usage and scheduler run data for the selected agent and time window. |  |  |
| TASK-020 | Update `frontend/src/app/usage/page.tsx` so clicking a usage record routes to `/runs` with the corresponding `run_id` and filter context instead of opening a page-local fixed overlay. |  |  |
| TASK-021 | Update `frontend/src/app/scheduler/page.tsx` so cron-job and scheduler-run review links route to `/runs` where applicable, while the page retains only authoring, metrics, and heartbeat-control responsibilities. |  |  |

### Implementation Phase 5

- GOAL-005: Enable trace exploration once persisted trace/audit data is exposed through backend APIs.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-022 | Add backend read APIs in `backend/api/` for persisted run/audit data. Create `backend/api/runs.py` for run detail if missing and `backend/api/traces.py` for tool-call and trace-event retrieval backed by `backend/storage/run_store.py` and existing audit files. Register the routes in `backend/app.py`. |  |  |
| TASK-023 | Extend `frontend/src/lib/api.ts` with typed clients for the new run-detail and trace endpoints, including correlation fields for `agent_id`, `session_id`, `run_id`, and trace/event identifiers. |  |  |
| TASK-024 | Create `frontend/src/components/traces/TraceFilterBar.tsx`, `frontend/src/components/traces/TraceEventList.tsx`, `frontend/src/components/traces/TraceDetail.tsx`, and `frontend/src/components/traces/CorrelationPanel.tsx`. |  |  |
| TASK-025 | Implement `frontend/src/app/traces/page.tsx` so the route supports URL-driven filtering and drill-in from `/runs`, `/sessions`, and `/`. If backend trace APIs are not complete, render an explicit unavailable state rather than a partial broken view. |  |  |

### Implementation Phase 6

- GOAL-006: Align tests, accessibility coverage, and regression protection with the new operator-console structure.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-026 | Add route-level rendering tests for `/sessions`, `/runs`, and `/traces` under `frontend/src/app/` or `frontend/src/components/` using Vitest and Testing Library. |  |  |
| TASK-027 | Add interaction tests for URL-state helpers, detail-drawer open/close behavior, and keyboard activation of clickable rows and tabs in `frontend/src/components/ui/` and the new route components. |  |  |
| TASK-028 | Add regression tests for chat auto-scroll behavior in `frontend/src/components/chat/ChatPanel.tsx` and keyboard resizing behavior in `frontend/src/components/layout/ResizeHandle.tsx`. |  |  |
| TASK-029 | Update or add backend API tests in `backend/tests/backend/` for any new run-detail or trace-explorer endpoints created in Phase 5. |  |  |

## 3. Alternatives

- **ALT-001**: Keep all new workflow features inside the existing workspace shell. Rejected because it preserves the current navigation and review bottleneck.
- **ALT-002**: Replace the current workspace-first product with a full observability-first rewrite. Rejected because it creates avoidable churn and delays value for the active operator workflow.
- **ALT-003**: Build `Trace Explorer` before `Sessions` and `Runs`. Rejected because the current API surface already supports faster wins in session and run navigation, while trace exploration still requires backend read APIs.

## 4. Dependencies

- **DEP-001**: Existing session APIs in `backend/api/sessions.py` and typed clients in `frontend/src/lib/api.ts`.
- **DEP-002**: Existing usage APIs and scheduler APIs already consumed by `frontend/src/app/usage/page.tsx` and `frontend/src/app/scheduler/page.tsx`.
- **DEP-003**: Persisted audit data written by `backend/storage/run_store.py`.
- **DEP-004**: New backend read APIs for run detail and trace detail are required before the `/traces` route can be fully implemented.
- **DEP-005**: Existing app-wide state in `frontend/src/lib/store.tsx`, which must remain the source of truth for live workspace streaming state during the migration.

## 5. Files

- **FILE-001**: `frontend/src/app/(console)/layout.tsx` - shared operator-console route layout.
- **FILE-002**: `frontend/src/components/layout/AppShell.tsx` - primary operator shell and navigation.
- **FILE-003**: `frontend/src/components/layout/Navbar.tsx` - refactor or remove in favor of `AppShell`.
- **FILE-004**: `frontend/src/lib/url-state.ts` - shared URL-state helpers.
- **FILE-005**: `frontend/src/components/layout/DetailDrawer.tsx` - shared route-aware detail drawer.
- **FILE-006**: `frontend/src/app/page.tsx` - workspace integration with URL-backed mobile panel state and improved splitter behavior.
- **FILE-007**: `frontend/src/components/layout/ResizeHandle.tsx` - keyboard-accessible splitter behavior.
- **FILE-008**: `frontend/src/components/chat/ChatPanel.tsx` - conditional auto-scroll and live-edge affordance.
- **FILE-009**: `frontend/src/app/sessions/page.tsx` - sessions route container.
- **FILE-010**: `frontend/src/components/sessions/*` - sessions route presentational components.
- **FILE-011**: `frontend/src/app/runs/page.tsx` - runs route container.
- **FILE-012**: `frontend/src/components/runs/*` - runs route presentational components.
- **FILE-013**: `frontend/src/lib/runs-model.ts` - normalized run view-model mapping.
- **FILE-014**: `frontend/src/app/traces/page.tsx` - trace explorer route container.
- **FILE-015**: `frontend/src/components/traces/*` - trace explorer presentational components.
- **FILE-016**: `frontend/src/app/usage/page.tsx` - route integration with shared shell and `/runs` drill-in.
- **FILE-017**: `frontend/src/app/scheduler/page.tsx` - route integration with shared shell and `/runs` drill-in.
- **FILE-018**: `frontend/src/lib/api.ts` - typed clients for any new run/trace endpoints.
- **FILE-019**: `backend/api/runs.py` - run-detail API if introduced.
- **FILE-020**: `backend/api/traces.py` - trace-detail API if introduced.
- **FILE-021**: `backend/storage/run_store.py` - persisted audit data dependency for trace reads.

## 6. Testing

- **TEST-001**: Verify `/sessions`, `/runs`, and `/traces` render inside the shared shell and respond to URL search params deterministically.
- **TEST-002**: Verify keyboard navigation and focus management for the operator shell, tabs, splitters, rows, and detail drawers.
- **TEST-003**: Verify the chat log stops auto-scrolling when the user scrolls away from the bottom and resumes when the user jumps back to the live edge.
- **TEST-004**: Verify Usage and Scheduler drill-ins route to `/runs` while preserving filter context.
- **TEST-005**: Verify trace explorer unavailable states render correctly when backend trace APIs are not available.
- **TEST-006**: Verify backend run-detail and trace-detail APIs return correlation identifiers and stable payload shapes if Phase 5 is implemented.

## 7. Risks & Assumptions

- **RISK-001**: The shared shell migration may create layout regressions if page-local nav assumptions remain in Usage or Scheduler.
- **RISK-002**: The current frontend pages are large container components; extracting them into route containers plus presentational components may expose implicit coupling not visible today.
- **RISK-003**: Trace Explorer scope can expand uncontrollably if the backend payload model is not constrained to a stable set of correlation fields and event types.
- **RISK-004**: Mixing usage-derived runs and scheduler-derived runs into one frontend ledger may produce inconsistent semantics unless normalization is explicit and tested.
- **ASSUMPTION-001**: Existing session, usage, and scheduler APIs are sufficient for the first operator-console release covering `Sessions` and `Runs`.
- **ASSUMPTION-002**: New trace-read APIs can be added without changing the live chat streaming contract.
- **ASSUMPTION-003**: The operator-console shell will remain compatible with the existing `AppProvider` store model during the migration.

## 8. Related Specifications / Further Reading

- `/Users/kai/.codex/worktrees/db3b/mini-openclaw-langchain/docs/plans/2026-03-06-frontend-operator-console-design.md`
- [Vercel Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
