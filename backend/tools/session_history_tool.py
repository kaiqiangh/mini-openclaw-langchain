from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import resolve_agent_root, resolve_project_root

if TYPE_CHECKING:
    from graph.agent import AgentManager
    from graph.checkpoint_session_repository import CheckpointSessionSnapshot


_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_T = TypeVar("_T")


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, _T] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - thread handoff
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise RuntimeError(str(error[0])) from error[0]
    return result["value"]


@dataclass
class SessionHistoryTool:
    runtime_root: Path
    config_base_dir: Path | None = None
    max_messages_default: int = 200
    _manager: AgentManager | None = field(default=None, init=False, repr=False)

    name: str = "session_history"
    description: str = "Read session message history for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def _agent_manager(self) -> AgentManager:
        if self._manager is None:
            from graph.agent import AgentManager

            manager = AgentManager()
            manager.initialize(
                resolve_project_root(self.runtime_root, self.config_base_dir)
            )
            self._manager = manager
        return self._manager

    def _load_snapshot(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool,
        include_live: bool,
    ) -> CheckpointSessionSnapshot:
        manager = self._agent_manager()
        repository = manager.get_session_repository(agent_id)
        return _run_async(
            repository.load_snapshot(
                agent_id=agent_id,
                session_id=session_id,
                archived=archived,
                include_live=include_live,
            )
        )

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        session_id = str(args.get("session_id", "")).strip()
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="session_id must match [A-Za-z0-9_.-]{1,128}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        archived = bool(args.get("archived", False))
        include_live = bool(args.get("include_live", True))
        max_messages = int(args.get("max_messages", self.max_messages_default))
        max_messages = max(1, min(5000, max_messages))

        try:
            agent_id, _agent_root = resolve_agent_root(
                runtime_root=self.runtime_root,
                config_base_dir=self.config_base_dir,
                requested_agent_id=requested_agent_id,
            )
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            snapshot = self._load_snapshot(
                agent_id=agent_id,
                session_id=session_id,
                archived=archived,
                include_live=include_live,
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except RuntimeError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INTERNAL",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        messages = list(snapshot.messages)
        truncated = False
        if len(messages) > max_messages:
            messages = messages[-max_messages:]
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "agent_id": agent_id,
                "session_id": session_id,
                "archived": archived,
                "message_count": len(messages),
                "messages": messages,
                "compressed_context": snapshot.compressed_context,
                "truncated": truncated,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {"resource": "session_history", "scope": "agent"}
