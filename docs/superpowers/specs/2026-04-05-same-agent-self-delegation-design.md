# Same-Agent Self-Delegation Design

**Date**: 2026-04-05  
**Status**: Approved in brainstorming, pending user review  
**Author**: Kai + Codex brainstorming session

## 1. Problem

The current delegate path does not match the intended product model.

The desired behavior is:

- `crypto-rd` should spawn its own child worker
- the child should keep `agent_id=crypto-rd`
- the child should inherit the same workspace, skills, memory, and runtime config
- the child should get a fresh isolated session/context
- the child should remain hidden from the normal session list
- the parent session should receive structured delegate status/results inline

The observed failure case is session `154c1623-fa24-44f0-a2ec-52c222b14974`, where `crypto-rd` used `agents_list`, reasoned about peer agents, and concluded delegation creation was not directly available. That is the wrong mental model. Delegation should feel like `crypto-rd` forking itself, not coordinating with other named agents.

## 2. Goals

- Make delegation a same-agent fork, not a cross-agent orchestration feature
- Preserve `agent_id` across parent and child execution
- Keep delegated child sessions hidden from normal operator session views
- Attach delegate lifecycle and results back into the parent session timeline
- Resolve child tool scope from per-agent delegation role presets
- Remove cross-agent discovery from model-executed chat flows

## 3. Non-Goals

- Nested delegation or sub-sub-agents
- Exposing delegated children as normal sessions by default
- Expanding role scopes beyond configured presets
- Building a generic multi-agent orchestration layer in this change

## 4. Product Decisions

### 4.1 Delegation Identity

Delegation is a hidden sub-session of the same agent.

- Parent: `agent_id=crypto-rd`, `session_id=<parent>`
- Child: `agent_id=crypto-rd`, `session_id=<sub_session_id>`

The child is not another agent and must never be presented as `default`, `elon-musk`, or any other peer agent.

### 4.2 Visibility

Delegated children are internal sessions.

- visible in parent delegate views and debug APIs
- hidden from normal `sessions_list` and standard session pages
- not counted as ordinary active sessions in operator-facing summaries unless an admin/debug mode is explicitly requested

### 4.3 Parent Result Consumption

Delegate completion is attached back to the parent timeline as a structured event. The parent can then read and reason over that result naturally in later turns without manually browsing hidden child sessions.

### 4.4 Tool Scoping

Child tool access is driven by agent-local role presets.

Example roles:

- `researcher`
- `analyst`
- `writer`

Each role resolves to a configured tool allowlist owned by the parent agent's runtime config. A delegate call may narrow that role scope further, but may not expand it.

### 4.5 Cross-Agent Tools

`agents_list` and other cross-agent discovery behaviors should not be available to model-executed chat runs for `crypto-rd` or its delegated children. Those capabilities remain available only to human/admin surfaces.

## 5. Architecture

### 5.1 Delegate Launch Model

When the parent tool loop invokes `delegate(...)`:

1. Read the current request's `agent_id` and `session_id`
2. Resolve the delegate role preset from that agent's delegation config
3. Create a hidden child `sub_session_id`
4. Register delegate metadata under the parent session
5. Launch a background child run using the same `agent_id`
6. Return `delegate_id`, `sub_session_id`, `status=running`

The child run uses the same workspace root, skills, memory, runtime config, and LLM routing as the parent agent. Only the session/context is new.

### 5.2 Hidden Internal Session

The child session is persisted for audit/debug but marked internal.

Required properties:

- linked to `parent_session_id`
- excluded from normal session listing
- retrievable through delegate-specific APIs or admin/debug views

This preserves auditability without polluting the operator's main session list.

### 5.3 Scoped Tool Context

The child receives a delegate-specific tool context:

- base toolset = role preset from delegation config
- optional narrowing = caller-provided subset
- blocked tools = explicit blocked list
- hard deny = `delegate`
- hard deny = `agents_list`

This gives the child a small, predictable tool surface while keeping the parent and child within the same agent identity.

### 5.4 Parent Timeline Attachment

Delegate lifecycle events are written into the parent session history as structured entries.

At minimum the parent timeline must be able to represent:

- delegate started
- delegate completed
- delegate failed
- delegate timed out

Each event should include a stable envelope rather than freeform text.

Recommended fields:

```json
{
  "delegate": {
    "delegate_id": "del_abc123",
    "sub_session_id": "sub_xyz789",
    "role": "researcher",
    "status": "completed",
    "summary": "Found three exchange endpoints and ranked them by quality.",
    "tools_used": ["web_search", "fetch_url"],
    "duration_ms": 4200
  }
}
```

The frontend should render this as a first-class delegated-task artifact in the parent chat.

## 6. Data Model

### 6.1 Delegation Config

Delegation becomes first-class runtime config instead of a dead standalone constant.

Each agent config owns:

```json
{
  "delegation": {
    "enabled": true,
    "max_per_session": 5,
    "default_timeout_seconds": 120,
    "max_timeout_seconds": 600,
    "allowed_tool_scopes": {
      "researcher": ["web_search", "fetch_url", "read_files", "search_knowledge_base"],
      "analyst": ["read_files", "read_pdf", "search_knowledge_base", "terminal"],
      "writer": ["read_files", "search_knowledge_base", "apply_patch"]
    }
  }
}
```

Validation rules:

- `enabled` may disable delegation per agent
- `max_per_session >= 1`
- `default_timeout_seconds <= max_timeout_seconds`
- each role scope must be non-empty
- each role scope must reference known tools only
- no role scope may include `delegate`
- optional per-call narrowing must be a subset of the resolved role scope

### 6.2 Delegate Registry State

The registry remains keyed by:

- `agent_id`
- `parent_session_id`
- `delegate_id`

It must also track:

- `sub_session_id`
- internal-session visibility flag
- resolved role scope
- attached parent timeline event IDs, if used

Persistence remains under:

```text
workspaces/<agent_id>/sessions/<parent_session_id>/delegates/<delegate_id>/
```

## 7. APIs And UI

### 7.1 Backend APIs

Delegate APIs remain session-scoped beneath the parent:

- `GET /api/v1/agents/{agent_id}/sessions/{session_id}/delegates`
- `GET /api/v1/agents/{agent_id}/sessions/{session_id}/delegates/{delegate_id}`

The backend may expose admin/debug access to the hidden child session, but the main UI should not depend on normal session-list visibility.

### 7.2 Frontend UI

The parent chat view shows delegated tasks inline from parent-attached delegate events and/or session-scoped delegate endpoints.

The main sessions page should not display hidden delegate child sessions by default.

The UI should support:

- running delegate indicator
- completed summary
- failure/timeout display
- optional expanded result details

## 8. Error Handling

### 8.1 Launch Failure

If the child cannot be created before execution starts:

- return a tool error immediately
- do not leave a fake running delegate behind

### 8.2 Runtime Failure

If the child fails after launch:

- mark delegate as `failed`
- persist the error under the delegate result directory
- attach a failure event to the parent timeline

### 8.3 Timeout

If the child exceeds timeout:

- mark `status=timeout`
- persist timeout diagnostics
- attach a timeout event to the parent timeline

### 8.4 Config Errors

If the role preset is missing or invalid:

- fail the delegate call immediately
- return a clear configuration error

## 9. Implementation Boundaries

The following boundaries must hold after this change:

- delegation uses the current request agent, never `default_agent_id`
- child sessions are same-agent hidden sub-sessions
- model-executed chat paths cannot use `agents_list`
- delegation config is parsed from runtime config, not ignored
- parent timeline attachment is structured and stable

## 10. Testing

### 10.1 Backend

Required coverage:

- delegate launch preserves `agent_id=crypto-rd`
- child sub-session uses a new `session_id`
- hidden child sessions are excluded from normal session listing
- role preset resolution works
- optional narrowing cannot expand role scope
- `agents_list` is unavailable to model-executed chat runs
- delegate completion writes a structured parent timeline event
- failed and timed-out delegates also attach parent events
- delegate APIs return parent-visible state correctly

### 10.2 Frontend

Required coverage:

- parent chat renders running/completed/failed delegate artifacts
- normal session list excludes hidden children
- delegate summaries remain visible after refresh via parent-scoped data

## 11. Migration Notes

- Existing delegate behavior that assumes `default_agent_id` is incorrect and should be replaced rather than preserved.
- Existing sessions without delegate artifacts remain valid.
- Existing operator/admin agent visibility can stay intact outside model-executed chat tool paths.

## 12. Recommended Sequence

1. Make delegation config first-class in runtime parsing
2. Fix delegate launch to use the current agent instead of `default_agent_id`
3. Introduce hidden child-session semantics
4. Attach structured delegate events to the parent timeline
5. Add session-scoped delegate APIs
6. Remove `agents_list` from model tool availability for `crypto-rd` chat flows
7. Update frontend to render parent-scoped delegated task artifacts
