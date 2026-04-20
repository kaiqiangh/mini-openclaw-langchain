# Delegation Completeness Design

Date: 2026-04-20
Status: Proposed
Owner: Codex

## Summary

This spec closes the remaining gap between "blocking delegation exists in runtime" and "delegation is a complete product feature".

The repository already contains the core backend work for blocking delegates:

- explicit `wait_for_result` launch semantics in the `delegate` tool
- runtime-owned waiting and result injection
- checkpoint persistence for blocking delegate state
- retry and fallback handling during delegate-result synthesis
- raw session-scoped API endpoints for delegate summary and detail

What is still missing is full-chain completeness. Today, the frontend only lists delegate summaries, does not fetch delegate detail, does not render the existing `DelegateResultCard`, and only polls delegate status while the parent chat stream is active. That means a parent response can finish while a non-blocking delegate is still running, and the operator UI may stop updating before the delegate reaches a terminal state.

The goal of this work is to make delegation complete across runtime, API, frontend, and regression validation, so the feature is usable and repeatably verifiable as a product capability rather than a partial backend primitive.

## Problem

The current implementation is close, but not complete:

1. Backend runtime correctness is strongly tested for blocking delegate orchestration, but the product contract depends on more than the runtime graph.
2. The API exposes both delegate list and delegate detail, but the frontend currently only consumes the list endpoint.
3. `DelegateResultCard` exists but is not wired into the chat UI.
4. Delegate polling in the frontend is tied to `isStreaming`, so it can stop after the parent stream completes even when one or more delegates are still `running`.
5. The current frontend tests do not verify the delegate UI path.
6. There is no explicit "delegation completeness" verification path that can be rerun to guard against regression.

The result is an inconsistent user experience:

- backend state may be correct
- delegate detail may exist on disk and through the API
- but the UI may not surface that detail or keep updating until terminal state

That is not a complete delegation feature.

## Goals

- Make delegation complete across backend state, API, frontend presentation, and validation.
- Preserve current blocking delegate behavior and non-blocking delegate behavior.
- Ensure delegate terminal results remain visible after streaming ends.
- Ensure failure and timeout states are preserved and surfaced end-to-end.
- Add repeatable regression coverage for the full delegation contract.

## Non-Goals

- This spec does not redesign the delegate runtime architecture introduced in the blocking delegate work.
- This spec does not introduce nested delegation.
- This spec does not add delegate-to-parent live streaming of sub-agent tokens.
- This spec does not redesign the visual language of the operator UI beyond the minimum needed to make delegation complete.

## Current Findings

### Backend

The backend already includes the important runtime pieces:

- `delegate` supports `wait_for_result`
- blocking delegates move the parent into a runtime-owned waiting path
- delegate result injection is explicit and tested
- synthesis retries and fallback guard against stale "still running" output
- checkpoint state round-trips blocking delegate runtime types

These pieces are necessary and should remain the foundation.

### API

The API already exposes:

- `GET /api/v1/agents/{agent_id}/sessions/{session_id}/delegates`
- `GET /api/v1/agents/{agent_id}/sessions/{session_id}/delegates/{delegate_id}`

The contract is raw and session-scoped, which is the right shape for the frontend.

### Frontend

The frontend currently has two product gaps:

1. `ChatPanel` renders only summary badges for delegates and never renders `DelegateResultCard`.
2. The store polls delegates only inside the "session is currently streaming" effect. Once the parent stream finishes, polling can stop before a non-blocking delegate reaches `completed`, `failed`, or `timeout`.

This is the main product-level incompleteness.

## Product Contract

Delegation is considered complete only if all of the following are true.

### 1. Blocking delegates

For `wait_for_result=true`:

- the parent run waits for all required delegates to reach terminal state
- the parent cannot silently continue ordinary business work while required delegates are unresolved
- delegate terminal results are injected before parent answer synthesis
- if a required delegate fails or times out, the parent answer is explicitly partial or incomplete

### 2. Non-blocking delegates

For `wait_for_result=false`:

- the parent may complete its own response independently
- delegate status remains observable after the parent response completes
- the operator UI continues to update until the delegate reaches terminal state

### 3. Restarts and resume

- checkpoint-backed runtime state preserves blocking delegate orchestration data
- delegate registry hydration preserves terminal delegate metadata for the session
- reopening or reloading a session does not hide already-known delegate outcomes

### 4. Operator visibility

The operator must be able to see:

- a running delegate summary
- a terminal delegate detail view
- timeout and failure details
- tool usage and duration when available

## Approach Options

### Option A: Frontend-only patch

Wire `DelegateResultCard`, fetch delegate detail, and extend polling.

Pros:

- smallest code delta
- fastest path to a visibly complete UI

Cons:

- assumes the backend contract is already sufficiently covered
- does not explicitly tighten product-level regression coverage

### Option B: Cross-layer completeness pass

Preserve current backend runtime architecture, close the frontend gaps, and add a dedicated regression matrix spanning runtime, API, frontend, and repeatable verification commands.

Pros:

- matches the actual product boundary
- addresses both feature behavior and future regression risk
- keeps architectural churn low

Cons:

- touches multiple layers
- slightly larger patch than a UI-only fix

### Option C: E2E-first rewrite

Start from an end-to-end browser workflow, then reshape whichever layers fail until the flow passes.

Pros:

- closest to user reality

Cons:

- slower to localize defects
- unnecessary when the root product gap is already identifiable

### Recommendation

Choose Option B.

The runtime work should remain intact. The missing work is not a new architecture; it is a cross-layer completion pass that turns the current pieces into a coherent feature.

## Detailed Design

### 1. Backend invariants remain explicit

The backend changes in this pass should be limited to targeted gap closure and verification, not a redesign.

The implementation must preserve these invariants:

- `wait_for_result=true` delegates are tracked as required dependencies
- resolved delegate results are injected into the parent context exactly once
- synthesis retry/fallback remains protected against stale tool-loop behavior
- checkpoint serialization continues to round-trip blocking delegate runtime types
- delegate registry continues to expose terminal detail for API consumers

If a backend defect is found while implementing the product closure work, it should be fixed narrowly against these invariants rather than through broader runtime refactoring.

### 2. Frontend delegate model becomes two-tiered

The frontend should treat delegates as:

- summary rows for the session-level list
- optional detail payloads for terminal delegates

The store should continue using `listDelegates(...)` as the primary polling source, but it must add detail fetching for delegates that are no longer `running`.

The expected behavior is:

- running delegates show up immediately in the "Delegated Tasks" area
- once a delegate reaches terminal state, the UI fetches detail for that delegate
- terminal delegates render the existing `DelegateResultCard`
- summary badges remain useful, but no longer represent the entire feature

### 3. Delegate polling must outlive parent streaming

Delegate polling must not be keyed only to `isStreaming`.

Instead, polling should continue while all of the following are true:

- the session is active and selected
- the session is not archived
- there is an active delegate poll condition, meaning:
  - the parent is streaming, or
  - there is at least one known delegate still in `running`, or
  - the session is freshly loaded and delegate state must be discovered

Polling may stop only when:

- the session is inactive or archived, or
- there are no delegates for the session, or
- all known delegates are terminal and all required detail payloads have been fetched

This is the key fix for non-blocking delegate completeness.

### 4. UI presentation

`ChatPanel` should present delegates in two layers:

- a compact summary strip for all delegates
- one or more terminal result cards below or adjacent to the summary strip

The display rules are:

- `running`: show summary row only
- `completed`: show summary row and detail card
- `failed`: show summary row and detail card with error emphasis
- `timeout`: show summary row and detail card with timeout emphasis

The current `DelegateResultCard` can be reused with light modifications if needed, but the existing component should be preferred over inventing a second terminal-result UI.

### 5. Regression coverage

The work must add or tighten coverage in four places.

#### Backend runtime

Keep the existing blocking delegate tests and add only what is needed to cover any newly discovered bug.

#### API contract

Delegate endpoint tests must continue to prove:

- session-scoped listing
- detail payload shape
- terminal detail visibility for completed and non-completed delegates

#### Frontend tests

Add tests for:

- delegate summary rendering in `ChatPanel`
- terminal delegate detail card rendering
- failure/timeout rendering behavior
- continued delegate polling or polling eligibility after parent streaming ends

#### Repeatable verification path

Document a single rerunnable validation path that includes:

- backend pytest
- frontend tests
- frontend build
- one delegate workflow verification path that proves both summary and detail behavior

The delegate workflow verification path can begin as a deterministic local/manual sequence if full browser automation is not yet justified, but it must be explicit and repeatable.

## Acceptance Criteria

This work is complete only when all of the following pass.

### Functional

- Blocking delegates still enforce runtime waiting and result injection.
- Non-blocking delegates continue to update in the UI after the parent stream finishes.
- Terminal delegates render detail content in the operator UI.
- Failed and timed-out delegates show their error state in the operator UI.
- Reloading an active session does not lose delegate visibility.

### Contract

- Delegate list and detail endpoints remain session-scoped and stable.
- Frontend delegate rendering uses the existing API contract rather than ad hoc filesystem assumptions.

### Verification

- `cd backend && ./.venv/bin/pytest -q`
- `cd frontend && npm run test:run`
- `cd frontend && npm run build`
- a documented delegation verification path is executed and recorded in the closeout

## Risks and Mitigations

### Risk: over-polling the delegate endpoints

Mitigation:

- keep polling scoped to the current active session only
- stop polling once all delegates are terminal and detail fetches are resolved
- reuse the existing best-effort polling pattern rather than introducing new long-lived streams

### Risk: duplicate or stale terminal cards

Mitigation:

- key terminal delegate detail by `delegate_id`
- treat list data as summary state and detail data as an idempotent overlay
- always let the latest terminal status win

### Risk: accidental backend churn

Mitigation:

- treat the current blocking runtime architecture as fixed unless a concrete failing test proves otherwise
- prefer narrow fixes and additive tests

## Implementation Outline

1. Audit backend and API invariants against the acceptance criteria.
2. Wire frontend terminal delegate detail into `ChatPanel`.
3. Decouple delegate polling from parent streaming-only lifetime.
4. Add frontend and API regression coverage for the completed flow.
5. Run the full validation path and record the evidence.

## Open Questions

There are no blocking product questions left for this pass.

The design assumes the feature should optimize for completeness and regression safety, not for introducing a new transport or UI paradigm.
