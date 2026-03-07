# Frontend Operator Console Design

Date: 2026-03-06
Status: Approved
Scope: Frontend information architecture, workflow design, and operator-facing observability UX

## Summary

The current frontend is strongest at live interaction inside the main workspace, but review and observability workflows are fragmented across the sidebar, chat transcript, Usage, and Scheduler pages. The next frontend wave should optimize for faster day-to-day operator workflow and richer traceability by keeping the live workspace intact while introducing dedicated operator views for sessions, runs, and traces.

## Current-State Review

### What is working

- The app already has a strong operator-console base: a live workspace shell, multi-agent context, file/runtime inspection, scheduler controls, and usage analytics.
- Separate top-level pages already exist for usage and scheduler workflows, which makes a route-based expansion feasible.
- The frontend has reusable UI primitives, local persistence for panel preferences, and an app-wide store for live workspace state.

### Current UX constraints

- Too many workflows are trapped inside the main workspace shell.
- Important review state is stored only in component state or local storage instead of the URL.
- The chat transcript is overloaded as both a live interaction surface and a debugging surface.
- Review drawers in Usage and Scheduler are useful but ad hoc rather than part of a consistent navigation model.

### Key frontend findings

- Split resizing is pointer-driven and not keyboard-operable.
- The chat log auto-scroll behavior pulls the user back to the bottom even while reviewing earlier output.
- Usage and Scheduler filters are not deep-linkable.
- Traceability is partial: the current UI exposes live tool/retrieval/debug information inside chat, but there is no dedicated cross-session trace review experience.

## Product Direction

The product should move toward a hybrid operator console.

- Keep the current workspace page for active execution.
- Promote review, inspection, and monitoring into dedicated pages.
- Preserve fast access to live controls from the workspace.
- Make investigation workflows linkable, repeatable, and filterable.

## Alternatives Considered

### 1. Expand only the current workspace shell

Pros:

- Lowest churn
- Fastest to ship

Cons:

- Keeps the current information-architecture problem intact
- Makes history and observability workflows harder to scale

### 2. Hybrid operator console with dedicated views

Pros:

- Best balance of speed, clarity, and extensibility
- Aligns with the existing Next.js route structure
- Separates live operation from historical investigation

Cons:

- Requires route and shared-state refactoring
- Requires backend support for trace exploration

### 3. Full observability-first rewrite

Pros:

- Strongest long-term admin-console model

Cons:

- Highest churn
- Highest delivery risk
- Risks slowing the active chat workflow

### Decision

Choose the hybrid operator console approach.

## Information Architecture

### Top-level views

- `Workspace`: live conversation, file/runtime inspection, quick trace preview
- `Sessions`: searchable session inbox and transcript review
- `Runs`: unified operational ledger across chat, cron, and heartbeat activity
- `Trace Explorer`: deep inspection of tool calls, retrievals, debug events, and correlations
- `Scheduler`: scheduler authoring and health controls
- `Usage`: token and cost analytics

### Navigation model

- Replace the current minimal top navigation with a stronger operator shell.
- Use route-level navigation for all primary workflows.
- Use URL state for filters, selected records, density mode, and detail panes when the state is review-oriented.
- Keep only truly live workspace state in the app store.

## Page Responsibilities

### Workspace

- Optimize for active work, not long-range review.
- Keep the current chat + inspector pairing.
- Add only lightweight trace preview and session context.
- Remove heavy history and observability tasks from the main chat shell.

### Sessions

- Search, filter, sort, and resume sessions across agents.
- Show session metadata, transcript, and related operational context.
- Support archived and active views without overloading the sidebar.

### Runs

- Provide a dense ledger for run outcomes, status, source, duration, and correlation identifiers.
- Unify operational review currently split between Usage and Scheduler.

### Trace Explorer

- Show tool calls, retrieval events, debug events, and linked run/session context.
- Preserve a trace preview inside Workspace, but centralize deep inspection here.

### Scheduler

- Stay focused on job creation, editing, heartbeat control, and scheduler health.
- Move run-history review emphasis into the Runs page.

### Usage

- Stay focused on cost, token, and model analytics.
- Link usage records to runs and sessions rather than acting as a mixed analytics/debugging page.

## Shared Components

- `AppShell`: primary navigation, current-agent context, health/status badges
- `ContextBar`: shared page-level filters
- `DetailDrawer`: route-aware side drawer for session, run, and trace detail
- `SavedViewBar`: optional saved filters and presets

## Route And State Model

### Route strategy

- Keep `/` as the live workspace route.
- Add `/sessions`, `/runs`, and `/traces`.
- Keep `/scheduler` and `/usage`.

### State boundaries

- App store:
  - active streaming session state
  - live chat messages
  - active agent context
  - optimistic stream updates
- URL state:
  - selected agent where page-level review depends on it
  - selected session, run, or trace
  - time window
  - status/source filters
  - density mode where useful
  - detail-drawer open state

### Data-flow structure

- Route container fetches and shapes page data.
- Shared hooks translate URL state into API requests.
- Presentational components render dense operator views without owning fetch logic.
- Correlation identifiers connect pages instead of duplicating business logic in each page.

## Correlation Model

The operator experience should use the following identifiers consistently:

- `agent_id`
- `session_id`
- `run_id`
- trace/event identifier
- `trigger_type`

This allows a user to move between session history, run history, and trace detail without losing context.

## UX And Accessibility Requirements

- Make split panels keyboard-operable.
- Stop auto-sticking the chat log to the bottom when the user is intentionally reviewing older messages.
- Replace ad hoc fixed overlays with a consistent detail-drawer pattern.
- Ensure row-based interactions are keyboard-accessible.
- Keep filters deep-linkable and restorable from the URL.
- Distinguish empty, loading, stale, and failed states visually.

## Implementation Priorities

### Priority 1

- New operator shell
- `Sessions` page
- URL-driven detail drawer
- Chat scroll behavior fix
- Accessible splitters

### Priority 2

- `Runs` page
- shared filter model across Sessions, Runs, Scheduler, and Usage
- correlation links between usage records, run records, and sessions

### Priority 3

- `Trace Explorer`
- richer trace capture and backend APIs for persisted audit/run data
- refactor of Scheduler and Usage into the new shell

## Backend Dependencies

### Already available

- session listing and history APIs
- usage summary and usage records APIs
- scheduler metrics, runs, failures, jobs, and heartbeat APIs

### Missing for the full design

- dedicated run-detail API for non-usage runs
- dedicated trace/audit read APIs for persisted tool-call and trace exploration
- normalized correlation payloads that join runs, sessions, and traces

`Trace Explorer` should therefore be planned as a later phase unless the backend work is included in the same initiative.

## Testing Expectations

- URL-state navigation tests
- keyboard interaction tests for splitters, tables, tabs, and drawers
- regression tests for chat auto-scroll behavior
- rendering tests for loading, empty, error, and dense-data states
- accessibility checks for headings, focus order, and drawer semantics

## Rollout Recommendation

Ship the new shell and the first two operator views before building the full trace experience.

Recommended initial release:

- operator navigation shell
- `Sessions`
- `Runs`
- route-aware detail drawer
- chat scroll fix
- keyboard-accessible splitters

This delivers workflow speed and observability value quickly while keeping the live workspace stable.
