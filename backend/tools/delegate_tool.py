from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.base import ToolContext
from tools.delegate_config import ALL_KNOWN_TOOLS, DELEGATE_DEFAULTS
from tools.delegate_registry import DelegateRegistry
from tools.policy import PermissionLevel

# Hard limit for task description length (chars)
_DELEGATE_MAX_TASK_CHARS = 4000

logger = logging.getLogger(__name__)


class DelegateArgs(BaseModel):
    task: str = Field(description="Natural language description of the sub-task to delegate")
    role: str = Field(default="researcher", description="Sub-agent role label")
    allowed_tools: list[str] = Field(description="List of tool names this sub-agent can use")
    blocked_tools: list[str] = Field(default=[], description="Explicitly blocked tools")
    timeout_seconds: int | None = Field(default=None, description="Max wall-clock seconds (max 600)")


def build_delegate_tool(
    *,
    agent_manager: Any,
    registry: DelegateRegistry,
    base_dir: Any,
    context: ToolContext,
) -> StructuredTool:
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
            runtime = agent_manager.get_runtime(agent_manager.default_agent_id)

            # Create sub-agent session
            await runtime.session_manager.create_session(
                sub_session_id,
                title=f"Sub-agent ({role}): {task[:60]}",
            )

            # Build tool context & runner for sub-agent
            from graph.runtime_types import RuntimeRequest

            from tools import get_all_tools, get_tool_runner
            from tools.base import ToolContext as TC
            from tools.langchain_tools import build_langchain_tools

            tool_runner = get_tool_runner(
                runtime.root_dir,
                audit_store=getattr(runtime, "audit_store", None),
            )

            scoped_tools = get_all_tools(
                runtime.root_dir,
                runtime.runtime_config,
                trigger_type="chat",
                config_base_dir=base_dir,
            )

            delegate_ctx = TC(
                workspace_root=runtime.root_dir,
                trigger_type="chat",
                explicit_enabled_tools=tuple(allowed_tools),
                explicit_blocked_tools=tuple(blocked_tools),
                session_id=sub_session_id,
            )

            langchain_tools = build_langchain_tools(
                tools=scoped_tools,
                runner=tool_runner,
                context=delegate_ctx,
            )

            # Invoke sub-agent via graph runtime
            graph_runtime = agent_manager.graph_registry.get("default")
            request = RuntimeRequest(
                message=task,
                history=[],
                session_id=sub_session_id,
                agent_id=agent_manager.default_agent_id,
                graph_name="default",
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

        except asyncio.TimeoutError:
            registry.mark_timeout(delegate_id)
            return
        except Exception as exc:
            logger.exception(f"Sub-agent {delegate_id} failed")
            registry.mark_failed(delegate_id, str(exc))

    def _run_sync(
        task: str,
        role: str = "researcher",
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        blocked = blocked_tools or []
        timeout = timeout_seconds or DELEGATE_DEFAULTS["default_timeout_seconds"]
        max_timeout = DELEGATE_DEFAULTS["max_timeout_seconds"]
        if timeout > max_timeout:
            timeout = max_timeout

        # -- Validation --
        if not task or not task.strip():
            return json.dumps(
                {"error": "task is required and must be non-empty"},
                ensure_ascii=False,
            )
        if not allowed_tools:
            return json.dumps(
                {"error": "allowed_tools is required and must be non-empty"},
                ensure_ascii=False,
            )
        if len(task) > _DELEGATE_MAX_TASK_CHARS:
            return json.dumps(
                {"error": f"task exceeds maximum length of {_DELEGATE_MAX_TASK_CHARS} characters"},
                ensure_ascii=False,
            )
        if "delegate" in allowed_tools:
            return json.dumps(
                {
                    "error": (
                        "'delegate' cannot be in allowed_tools "
                        "(nested delegation blocked)"
                    )
                },
                ensure_ascii=False,
            )
        unknown = [t for t in allowed_tools if t not in ALL_KNOWN_TOOLS]
        if unknown:
            return json.dumps(
                {"error": f"Unknown tools: {', '.join(unknown)}"},
                ensure_ascii=False,
            )

        agent_id = str(
            getattr(agent_manager, "default_agent_id", "default")
        )
        session_id = context.session_id or "unknown"

        if not registry.check_max_per_session(
            agent_id, session_id, DELEGATE_DEFAULTS["max_per_session"],
        ):
            return json.dumps(
                {
                    "error": (
                        f"Maximum {DELEGATE_DEFAULTS['max_per_session']} "
                        f"delegates per session reached"
                    )
                },
                ensure_ascii=False,
            )

        # -- Register --
        reg = registry.register(
            agent_id=agent_id,
            parent_session_id=session_id,
            task=task.strip(),
            role=role,
            allowed_tools=list(allowed_tools),
            blocked_tools=list(blocked),
            timeout_seconds=timeout,
        )
        delegate_id = reg["delegate_id"]
        sub_session_id = reg["session_id"]

        # -- Launch async task --
        # In production this runs inside graph_runtime.ainvoke() which always
        # has a running event loop.  During unit tests (sync func() call) that
        # loop doesn't exist — we skip scheduling the task, the delegate is
        # already registered as "running" above.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            task_ref = loop.create_task(
                _run_sub_agent(
                    task=task.strip(),
                    role=role,
                    allowed_tools=list(allowed_tools),
                    blocked_tools=list(blocked),
                    timeout_seconds=timeout,
                    delegate_id=delegate_id,
                    sub_session_id=sub_session_id,
                ),
                name=f"delegate_{task[:32]}",
            )
            registry.set_task_ref(delegate_id, task_ref)

        return json.dumps(
            {
                "delegate_id": delegate_id,
                "status": "running",
                "session_id": sub_session_id,
                "role": role,
                "note": (
                    f"Sub-agent '{role}' launched. "
                    "Use delegate_status to check progress."
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        name="delegate",
        description=(
            f"Delegate a sub-task to an isolated agent instance with scoped "
            f"tool access. Runs independently. Use delegate_status to check "
            f"progress. No nesting. Max {DELEGATE_DEFAULTS['max_per_session']} "
            f"per session."
        ),
        func=_run_sync,
        args_schema=DelegateArgs,
    )


class DelegateStatusArgs(BaseModel):
    delegate_id: str = Field(description="Delegate ID returned from delegate tool")


def build_delegate_status_tool(*, registry: DelegateRegistry) -> StructuredTool:
    def _run_status(delegate_id: str) -> str:
        state = registry.get_status(delegate_id)
        if not state:
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
