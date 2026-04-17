from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from config import DelegationConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.base import ToolContext
from tools.delegate_config import ALL_KNOWN_TOOLS, DELEGATE_DEFAULTS
from tools.delegate_registry import DelegateRegistry
from tools.policy import PermissionLevel

# Hard limit for task description length (chars)
_DELEGATE_MAX_TASK_CHARS = 4000
_DELEGATE_INLINE_WAIT_SECONDS = 5.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DelegateLaunch:
    agent_id: str
    parent_session_id: str
    task: str
    role: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    timeout_seconds: int
    delegate_id: str
    sub_session_id: str


class DelegateArgs(BaseModel):
    task: str = Field(description="Natural language description of the sub-task to delegate")
    role: str = Field(default="researcher", description="Sub-agent role label")
    allowed_tools: list[str] = Field(default=[], description="Optional subset of the role's tool scope")
    blocked_tools: list[str] = Field(default=[], description="Explicitly blocked tools")
    timeout_seconds: int | None = Field(default=None, description="Max wall-clock seconds (max 600)")


def _delegate_request_message(*, role: str, task: str) -> str:
    return "\n".join(
        [
            f"You are an isolated delegate child session acting as a {role}.",
            "You do not inherit the parent session context or transcript.",
            "Work only from this task, the current workspace, and the tools explicitly available to you.",
            "Do not inspect other sessions, delegate artifacts, or storage internals unless the task explicitly requires it.",
            "If the task names workspace paths or directories, stay within those paths unless broader exploration is explicitly required.",
            "When the task is about local workspace content, prefer local files and knowledge sources over web search.",
            "Return a concise final answer that the parent agent can report back to the user.",
            "",
            "Original delegated task:",
            task,
        ]
    )


def build_delegate_tool(
    *,
    agent_manager: Any,
    registry: DelegateRegistry,
    base_dir: Any,
    context: ToolContext,
) -> StructuredTool:
    def _delegation_config() -> DelegationConfig:
        runtime = agent_manager.get_runtime(context.agent_id)
        return runtime.runtime_config.delegation

    async def _append_parent_delegate_event(
        *,
        agent_id: str,
        session_id: str,
        content: str,
        delegate_payload: dict[str, Any],
    ) -> None:
        repository = agent_manager.get_session_repository(agent_id)
        await repository.append_message(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=content,
            event_kind="delegate",
            delegate=delegate_payload,
        )

    async def _run_sub_agent(
        task: str,
        role: str,
        allowed_tools: list[str],
        blocked_tools: list[str],
        timeout_seconds: int,
        delegate_id: str,
        sub_session_id: str,
    ) -> None:
        """Execute sub-agent in background. Called via asyncio.create_task."""
        try:
            runtime = agent_manager.get_runtime(context.agent_id)

            # Create sub-agent session
            await runtime.session_manager.create_session(
                sub_session_id,
                title=f"Sub-agent ({role}): {task[:60]}",
                hidden=True,
                internal=True,
                metadata={
                    "session_kind": "delegate_child",
                    "parent_session_id": context.session_id,
                    "delegate_id": delegate_id,
                    "delegate_role": role,
                },
            )
            from graph.runtime_types import RuntimeRequest

            # Invoke sub-agent via graph runtime
            graph_runtime = agent_manager.graph_registry.resolve("default")
            request = RuntimeRequest(
                message=_delegate_request_message(role=role, task=task),
                history=[],
                session_id=sub_session_id,
                agent_id=context.agent_id,
                graph_name="default",
                explicit_enabled_tools=list(allowed_tools),
                explicit_blocked_tools=list(blocked_tools),
            )

            if timeout_seconds is not None:
                result = await asyncio.wait_for(
                    graph_runtime.invoke(request), timeout=float(timeout_seconds),
                )
            else:
                result = await graph_runtime.invoke(request)

            # Extract results
            messages = getattr(result, "messages", [])
            summary = ""
            tools_used_set: set[str] = set()
            steps = 0
            for msg in messages:
                msg_type = getattr(msg, "type", "") or getattr(msg, "role", "")
                content = getattr(msg, "content", "")
                if msg_type in ("assistant", "ai", "agent"):
                    if content:
                        summary = str(content)[-2000:]
                    steps += 1
                if msg_type in ("tool", "tool_result"):
                    tools_used_set.add(getattr(msg, "name", "tool"))

            token_usage = getattr(result, "token_usage", {})
            registry.mark_completed(
                delegate_id,
                {
                    "summary": summary,
                    "steps": steps,
                    "tools_used": list(tools_used_set),
                    "token_usage": (
                        token_usage if isinstance(token_usage, dict) else {}
                    ),
                },
            )
            completed_state = registry.get_status(delegate_id)
            await _append_parent_delegate_event(
                agent_id=context.agent_id,
                session_id=context.session_id or "unknown",
                content=(
                    f"Delegate completed ({role}): {summary[:240].strip() or 'No summary returned.'}"
                ),
                delegate_payload={
                    "delegate_id": delegate_id,
                    "status": "completed",
                    "role": role,
                    "task": task,
                    "sub_session_id": sub_session_id,
                    "summary": summary,
                    "tools_used": list(tools_used_set),
                    "steps_completed": steps,
                    "duration_ms": completed_state.duration_ms if completed_state else 0,
                    "token_usage": (
                        token_usage if isinstance(token_usage, dict) else {}
                    ),
                },
            )

        except asyncio.TimeoutError:
            registry.mark_timeout(delegate_id)
            timeout_state = registry.get_status(delegate_id)
            await _append_parent_delegate_event(
                agent_id=context.agent_id,
                session_id=context.session_id or "unknown",
                content=f"Delegate timed out ({role}): {task[:240]}",
                delegate_payload={
                    "delegate_id": delegate_id,
                    "status": "timeout",
                    "role": role,
                    "task": task,
                    "sub_session_id": sub_session_id,
                    "duration_ms": timeout_state.duration_ms if timeout_state else 0,
                },
            )
            return
        except Exception as exc:
            logger.exception(f"Sub-agent {delegate_id} failed")
            registry.mark_failed(delegate_id, str(exc))
            failed_state = registry.get_status(delegate_id)
            await _append_parent_delegate_event(
                agent_id=context.agent_id,
                session_id=context.session_id or "unknown",
                content=f"Delegate failed ({role}): {str(exc)[:240]}",
                delegate_payload={
                    "delegate_id": delegate_id,
                    "status": "failed",
                    "role": role,
                    "task": task,
                    "sub_session_id": sub_session_id,
                    "error": str(exc),
                    "duration_ms": failed_state.duration_ms if failed_state else 0,
                },
            )

    def _prepare_delegate_launch(
        *,
        task: str,
        role: str,
        allowed_tools: list[str] | None,
        blocked_tools: list[str] | None,
        timeout_seconds: int | None,
    ) -> tuple[str | None, _DelegateLaunch | None]:
        delegation_config = _delegation_config()
        if not delegation_config.enabled:
            return (
                json.dumps(
                    {"error": "delegation is disabled in runtime config"},
                    ensure_ascii=False,
                ),
                None,
            )
        blocked = blocked_tools or []
        timeout = timeout_seconds or delegation_config.default_timeout_seconds
        max_timeout = delegation_config.max_timeout_seconds
        if timeout > max_timeout:
            timeout = max_timeout

        if not task or not task.strip():
            return (
                json.dumps(
                    {"error": "task is required and must be non-empty"},
                    ensure_ascii=False,
                ),
                None,
            )
        normalized_task = task.strip()
        if len(normalized_task) > _DELEGATE_MAX_TASK_CHARS:
            return (
                json.dumps(
                    {"error": f"task exceeds maximum length of {_DELEGATE_MAX_TASK_CHARS} characters"},
                    ensure_ascii=False,
                ),
                None,
            )
        role_scope = delegation_config.allowed_tool_scopes.get(role)
        if not role_scope:
            return (
                json.dumps(
                    {"error": f"Unknown delegate role: {role}"},
                    ensure_ascii=False,
                ),
                None,
            )
        resolved_allowed_tools = list(role_scope)
        if allowed_tools:
            requested_tools = list(
                dict.fromkeys(
                    str(item).strip() for item in allowed_tools if str(item).strip()
                )
            )
            if "delegate" in requested_tools:
                return (
                    json.dumps(
                        {
                            "error": (
                                "'delegate' cannot be in allowed_tools "
                                "(nested delegation blocked)"
                            )
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )
            disallowed = [tool for tool in requested_tools if tool not in role_scope]
            if disallowed:
                return (
                    json.dumps(
                        {
                            "error": (
                                "allowed_tools must be a subset of the selected role scope; "
                                f"invalid: {', '.join(disallowed)}"
                            )
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )
            resolved_allowed_tools = requested_tools
        if "delegate" in resolved_allowed_tools:
            return (
                json.dumps(
                    {
                        "error": (
                            "'delegate' cannot be in allowed_tools "
                            "(nested delegation blocked)"
                        )
                    },
                    ensure_ascii=False,
                ),
                None,
            )
        unknown = [item for item in resolved_allowed_tools if item not in ALL_KNOWN_TOOLS]
        if unknown:
            return (
                json.dumps(
                    {"error": f"Unknown tools: {', '.join(unknown)}"},
                    ensure_ascii=False,
                ),
                None,
            )

        agent_id = context.agent_id or str(
            getattr(agent_manager, "default_agent_id", "default")
        )
        session_id = context.session_id or "unknown"

        if not registry.check_max_per_session(
            agent_id, session_id, delegation_config.max_per_session,
        ):
            return (
                json.dumps(
                    {
                        "error": (
                            f"Maximum {delegation_config.max_per_session} "
                            f"delegates per session reached"
                        )
                    },
                    ensure_ascii=False,
                ),
                None,
            )

        reg = registry.register(
            agent_id=agent_id,
            parent_session_id=session_id,
            task=normalized_task,
            role=role,
            allowed_tools=list(resolved_allowed_tools),
            blocked_tools=list(blocked),
            timeout_seconds=timeout,
        )
        return (
            None,
            _DelegateLaunch(
                agent_id=agent_id,
                parent_session_id=session_id,
                task=normalized_task,
                role=role,
                allowed_tools=list(resolved_allowed_tools),
                blocked_tools=list(blocked),
                timeout_seconds=timeout,
                delegate_id=reg["delegate_id"],
                sub_session_id=reg["session_id"],
            ),
        )

    def _schedule_delegate(
        loop: asyncio.AbstractEventLoop,
        launch: _DelegateLaunch,
    ) -> asyncio.Task[None]:
        loop.create_task(
            _append_parent_delegate_event(
                agent_id=launch.agent_id,
                session_id=launch.parent_session_id,
                content=f"Delegate started ({launch.role}): {launch.task[:240]}",
                delegate_payload={
                    "delegate_id": launch.delegate_id,
                    "status": "started",
                    "role": launch.role,
                    "task": launch.task,
                    "sub_session_id": launch.sub_session_id,
                    "allowed_tools": list(launch.allowed_tools),
                    "blocked_tools": list(launch.blocked_tools),
                },
            )
        )
        task_ref = loop.create_task(
            _run_sub_agent(
                task=launch.task,
                role=launch.role,
                allowed_tools=list(launch.allowed_tools),
                blocked_tools=list(launch.blocked_tools),
                timeout_seconds=launch.timeout_seconds,
                delegate_id=launch.delegate_id,
                sub_session_id=launch.sub_session_id,
            ),
            name=f"delegate_{launch.task[:32]}",
        )
        registry.set_task_ref(launch.delegate_id, task_ref)
        return task_ref

    def _delegate_payload(launch: _DelegateLaunch) -> str:
        state = registry.get_status(launch.delegate_id)
        payload: dict[str, Any] = {
            "delegate_id": launch.delegate_id,
            "status": state.status if state is not None else "running",
            "session_id": launch.sub_session_id,
            "role": launch.role,
        }
        if state is None or state.status == "running":
            payload["note"] = (
                f"Sub-agent '{launch.role}' launched. "
                "Use delegate_status to check progress."
            )
        elif state.status == "completed":
            payload["result_summary"] = state.result_summary or ""
            payload["steps_completed"] = state.steps_completed
            payload["tools_used"] = list(state.tools_used)
            payload["token_usage"] = dict(state.token_usage)
            payload["duration_ms"] = state.duration_ms
        elif state.status in {"failed", "timeout"}:
            payload["error_message"] = state.error_message or "Sub-agent failed"
            payload["duration_ms"] = state.duration_ms
        return json.dumps(payload, ensure_ascii=False)

    def _run_sync(
        task: str,
        role: str = "researcher",
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        error_payload, launch = _prepare_delegate_launch(
            task=task,
            role=role,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            timeout_seconds=timeout_seconds,
        )
        if error_payload is not None:
            return error_payload

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and launch is not None:
            _schedule_delegate(loop, launch)

        return _delegate_payload(launch)

    async def _run_async(
        task: str,
        role: str = "researcher",
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        error_payload, launch = _prepare_delegate_launch(
            task=task,
            role=role,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            timeout_seconds=timeout_seconds,
        )
        if error_payload is not None:
            return error_payload

        task_ref = _schedule_delegate(asyncio.get_running_loop(), launch)
        wait_seconds = min(
            _DELEGATE_INLINE_WAIT_SECONDS,
            float(launch.timeout_seconds),
        )
        if wait_seconds > 0:
            try:
                await asyncio.wait_for(asyncio.shield(task_ref), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
        return _delegate_payload(launch)

    return StructuredTool.from_function(
        name="delegate",
        description=(
            f"Delegate a sub-task to an isolated agent instance with scoped "
            f"tool access. Runs independently. Use delegate_status to check "
            f"progress. No nesting. Max {DELEGATE_DEFAULTS['max_per_session']} "
            f"per session."
        ),
        func=_run_sync,
        coroutine=_run_async,
        args_schema=DelegateArgs,
    )


class DelegateStatusArgs(BaseModel):
    delegate_id: str = Field(description="Delegate ID returned from delegate tool")


def build_delegate_status_tool(
    *,
    registry: DelegateRegistry,
    context: ToolContext,
) -> StructuredTool:
    def _run_status(delegate_id: str) -> str:
        state = registry.get_status(delegate_id)
        if (
            not state
            or state.agent_id != context.agent_id
            or state.parent_session_id != (context.session_id or "unknown")
        ):
            return json.dumps({"error": f"Delegate not found: {delegate_id}"}, ensure_ascii=False)

        result: dict[str, Any] = {
            "delegate_id": state.delegate_id,
            "status": state.status,
            "role": state.role,
            "task": state.task,
            "sub_session_id": state.sub_session_id,
            "created_at": state.created_at,
        }
        if state.status in ("completed", "failed", "timeout"):
            result["completed_at"] = state.completed_at
            result["duration_ms"] = state.duration_ms
        if state.status == "completed":
            result["result_summary"] = state.result_summary
            result["steps_completed"] = state.steps_completed
            result["tools_used"] = state.tools_used
            result["token_usage"] = state.token_usage
        if state.status in ("failed", "timeout"):
            result["error_message"] = state.error_message or "Sub-agent timed out"
        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        name="delegate_status",
        description="Check the status of a delegated sub-agent by its delegate_id",
        func=_run_status,
        args_schema=DelegateStatusArgs,
    )
