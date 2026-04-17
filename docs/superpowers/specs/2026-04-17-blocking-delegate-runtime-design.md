# Blocking Delegate Runtime Design

Date: 2026-04-17
Status: Proposed
Owner: Codex

## Summary

This spec defines runtime-enforced blocking semantics for delegated sub-agents.

Today, a parent agent can launch a delegate, observe that it is still `running`, and then continue executing the same task itself. That produces misleading outcomes: the delegate may time out or fail, while the parent still emits a complete-looking final answer assembled from its own fallback work.

The new behavior adds an explicit `wait_for_result` flag to the `delegate` tool. When a parent run launches one or more delegates with `wait_for_result=true`, the runtime treats those delegates as required dependencies for the current answer. The parent run is suspended until all such delegates reach a terminal state. Once they do, the runtime injects the terminal delegate results back into the parent context and resumes normal reasoning. If any required delegate failed or timed out, the parent may still answer, but it must do so as a partial or incomplete result rather than a full-success final answer.

This is a runtime contract change, not just a prompt change.

## Problem

The current delegation model has two conflicting behaviors:

1. A parent can launch a delegate for a task that is required for the current answer.
2. The parent can continue reading files, calling tools, and writing a final answer before the delegate returns.

That breaks the meaning of delegation. The delegate becomes an optional background attempt rather than a required dependency.

The failure mode is already visible in real sessions:

- a delegate child session is created correctly
- the delegate later times out
- the parent still produces a polished final answer using its own fallback work

This makes delegate failure hard to detect from the user-facing answer and defeats the purpose of using a specialist sub-agent in the first place.

## Goals

- Make blocking delegation explicit and testable.
- Ensure the parent run waits for required delegate results before continuing normal reasoning.
- Prevent the parent from redoing the delegated task while a required delegate is still running.
- Preserve the existing non-blocking delegate behavior for background or optional tasks.
- Preserve hidden child-session isolation.
- Ensure failed or timed-out required delegates cannot be presented as successful complete answers.

## Non-Goals

- This spec does not redesign delegate child tool scopes or path restrictions.
- This spec does not change frontend delegate UI beyond what is needed to consume existing runtime behavior.
- This spec does not introduce nested delegation.
- This spec does not redesign delegate transport or add a new delegate streaming API.

## Locked Product Decisions

### 1. Blocking is explicit

The `delegate` tool gains a new argument:

- `wait_for_result: bool = false`

Only delegates launched with `wait_for_result=true` block the current parent run.

### 2. Blocking is conditional, not universal

Non-blocking delegates continue to work as they do today. This spec only affects delegates that are explicitly marked as required dependencies for the current answer.

### 3. Multiple blocking delegates are allowed

The same parent run may launch multiple delegates with `wait_for_result=true`.

The parent run must wait until all blocking delegates launched in that run reach a terminal state:

- `completed`
- `failed`
- `timeout`

### 4. Failure does not become silent success

If one or more required delegates fail or time out, the parent may still produce a best-effort answer. However, the parent must present that answer as partial or incomplete. It must not produce a complete-looking successful final answer that hides the delegate failure.

### 5. Results are auto-injected and still queryable

When blocking delegates reach terminal state:

- the runtime automatically injects their terminal results into the parent context
- `delegate_status` remains available for diagnostics and explicit follow-up queries

### 6. Runtime guard is required

This behavior must be enforced by runtime state and control flow, not only by tool descriptions or prompt instructions.

## User-Visible Semantics

### Non-blocking delegate

If the parent calls:

```json
{
  "task": "...",
  "role": "researcher",
  "wait_for_result": false
}
```

the delegate behaves like a background task:

- the parent may continue its own reasoning
- the parent may still call `delegate_status`
- the delegate is not treated as a required dependency for the current answer

### Blocking delegate

If the parent calls:

```json
{
  "task": "...",
  "role": "researcher",
  "wait_for_result": true
}
```

the delegate becomes a required dependency for the current answer:

- the parent run enters a waiting state
- the parent may not continue with ordinary business tools or normal answer synthesis
- the runtime waits for all blocking delegates launched in that run to reach terminal state
- the runtime injects their terminal results
- only then may the parent continue normal reasoning

### Blocking failure outcome

If any required delegate reaches `failed` or `timeout`:

- the parent may continue after terminal results are injected
- the parent may produce a best-effort answer
- that answer must explicitly communicate incompleteness, uncertainty, or degraded confidence

The runtime must not allow the parent to silently convert a required delegate failure into a polished full-success answer.

## Runtime Contract

### Delegate Tool Schema

The `delegate` tool adds:

- `wait_for_result: bool = false`

The tool result remains a normal successful tool payload, but when `wait_for_result=true` it must also mark the launch as a blocking dependency for the current run.

The delegate tool itself does not implement the waiting loop. It only registers the delegate and returns the metadata needed by the runtime.

### Runtime Graph State

`RuntimeGraphState` gains:

- `pending_blocking_delegates: list[BlockingDelegateRef]`
- `resolved_delegate_results: list[ResolvedDelegateResult]`
- `delegate_waiting: bool`

`BlockingDelegateRef` contains at least:

- `delegate_id`
- `role`
- `task`
- `sub_session_id`

`ResolvedDelegateResult` contains at least:

- `delegate_id`
- `role`
- `task`
- `status`
- `result_summary`
- `tools_used`
- `duration_ms`
- `error_message`

### Waiting Transition

After a tool step, if one or more `delegate` calls were launched with `wait_for_result=true`:

1. the runtime appends them to `pending_blocking_delegates`
2. `delegate_waiting` becomes `true`
3. the current run stops normal reasoning progression

### Waiting Behavior

While `delegate_waiting=true`:

- the parent run is suspended from ordinary business execution
- the runtime does not allow the parent to continue with:
  - `read_files`
  - `terminal`
  - `fetch_url`
  - `web_search`
  - `search_knowledge_base`
  - or any other tool that would let it redo the delegated task
- the runtime may perform minimal internal control actions needed to observe delegate lifecycle state

This waiting behavior is runtime-owned. It must not depend on the model choosing to “behave correctly”.

### Resume Condition

The parent run resumes only when every item in `pending_blocking_delegates` has reached terminal state.

At that point the runtime:

1. materializes one `ResolvedDelegateResult` per blocking delegate
2. appends those results to `resolved_delegate_results`
3. clears `pending_blocking_delegates`
4. sets `delegate_waiting=false`
5. resumes ordinary model reasoning

## Delegate Result Injection

The runtime must inject blocking delegate terminal results automatically before the parent resumes.

This injection is an internal runtime mechanism, not a user-visible chat message requirement. Before the next parent model step, the runtime must append one synthetic internal context message that summarizes all terminal blocking delegate results for the current run. That synthetic message is part of model input only; it is not rendered as a normal user-visible assistant message.

Each injected result must include:

- delegate identity
- delegated task
- terminal status
- result summary when completed
- error or timeout detail when not completed
- tool usage summary
- duration

The injected context must also include an explicit instruction layer:

- `completed` delegate results may be used as ordinary task outputs
- `failed` or `timeout` delegate results indicate an incomplete dependency
- if any required dependency failed, the final answer must explicitly state that it is partial or incomplete

`delegate_status` remains supported, but it is no longer required for the normal blocking flow.

## Failure Semantics

### Completed

If all required delegates complete successfully:

- the parent may proceed normally
- the final answer may be a normal complete answer

### Failed or Timeout

If one or more required delegates fail or time out:

- the parent may proceed after terminal injection
- the final answer must explicitly disclose that a required delegate failed or timed out
- the answer must be framed as partial, best-effort, or incomplete

Forbidden behavior:

- presenting a complete-looking final answer without disclosing that a required delegate failed
- treating a failed or timed-out required delegate as if it had produced a successful result

## Control-Flow Rules

### Rule 1: Blocking delegates are run-scoped

Blocking applies only to the current parent run, not the entire session forever.

Future turns may proceed normally after the blocked run reaches its terminal answer.

### Rule 2: Parent cannot silently take over the same task

Once a blocking delegate exists, the parent must not continue with business tools to perform the same work in parallel.

This is the core regression guard for sessions like `00594389-19f5-4f50-8a86-ca5e9adb9595`, where the parent kept reading local files and composing a full report even while the child was still running.

### Rule 3: Hidden session isolation stays intact

This spec does not weaken child-session isolation:

- child sessions remain hidden and internal
- ordinary session APIs still return `404`
- `session_history` must continue to reject hidden/internal child sessions

## Testing Requirements

Backend coverage must include:

### Delegate Tool

- `wait_for_result=false` preserves existing background behavior
- `wait_for_result=true` marks the launch as blocking metadata for the current run

### Runtime Blocking

- launching one blocking delegate transitions the parent run into waiting
- launching multiple blocking delegates waits for all of them
- while waiting, the runtime does not continue parent-side business tool execution
- once all blocking delegates are terminal, the runtime resumes normal reasoning

### Result Injection

- completed delegate results are auto-injected before parent resume
- failed and timeout delegate results are auto-injected with explicit failure semantics
- `delegate_status` remains available and consistent with injected terminal state

### Final Answer Semantics

- if all required delegates completed, the final answer may be complete
- if any required delegate failed or timed out, the final answer must contain explicit incomplete/partial semantics
- the old regression must fail: the parent must not emit a polished complete answer while a required delegate is still running or after it failed silently

### Regression Coverage

- hidden child-session isolation still works
- non-blocking delegates still behave as before

## Implementation Scope

Primary files expected to change:

- `backend/tools/delegate_tool.py`
- `backend/graph/runtime_types.py`
- `backend/graph/default_graph_runtime.py`
- `backend/graph/tool_execution.py` if needed for envelope propagation

This spec intentionally avoids frontend work in the first pass. The runtime contract must be stable before any UI changes depend on it.

## Out-of-Scope Follow-Up

The following issue remains real but is not solved by this spec:

- delegate child path and tool scope tightening for local-file tasks

That should be handled in a separate design, because it is orthogonal to the runtime blocking contract defined here.
