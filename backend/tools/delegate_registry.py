from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DelegateState:
    """Immutable-ish snapshot of a sub-agent's lifecycle state."""

    delegate_id: str
    agent_id: str
    parent_session_id: str
    sub_session_id: str
    task: str
    role: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    timeout_seconds: int | None
    task_ref: Any = None
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result_summary: str | None = None
    steps_completed: int = 0
    tools_used: list[str] = field(default_factory=list)
    duration_ms: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    error_message: str | None = None
    result_dir: Path | None = None


class DelegateRegistry:
    """In-memory registry for sub-agent lifecycle with disk persistence."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._delegates: dict[str, DelegateState] = {}

    def register(
        self,
        agent_id: str,
        parent_session_id: str,
        task: str,
        role: str,
        allowed_tools: list[str],
        blocked_tools: list[str],
        timeout_seconds: int | None,
    ) -> dict[str, str]:
        """Register a new delegate sub-agent.

        Returns dict with *delegate_id*, *session_id* (sub-session), and *role*.
        """
        delegate_id = f"del_{uuid.uuid4().hex[:8]}"
        sub_session_id = f"sub_{uuid.uuid4().hex[:8]}"
        result_dir = (
            self.base_dir
            / "workspaces"
            / agent_id
            / "sessions"
            / parent_session_id
            / "delegates"
            / delegate_id
        )
        result_dir.mkdir(parents=True, exist_ok=True)

        state = DelegateState(
            delegate_id=delegate_id,
            agent_id=agent_id,
            parent_session_id=parent_session_id,
            sub_session_id=sub_session_id,
            task=task,
            role=role,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            timeout_seconds=timeout_seconds,
            status="running",
            result_dir=result_dir,
        )
        self._delegates[delegate_id] = state

        # Persist minimal config so a restart can reconstruct
        (result_dir / "config.json").write_text(
            json.dumps(
                {
                    "task": task,
                    "role": role,
                    "allowed_tools": allowed_tools,
                    "blocked_tools": blocked_tools,
                    "sub_session_id": sub_session_id,
                    "created_at": state.created_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "delegate_id": delegate_id,
            "session_id": sub_session_id,
            "role": role,
        }

    def get_status(self, delegate_id: str) -> DelegateState | None:
        """Return the current state for a delegate, or None."""
        return self._delegates.get(delegate_id)

    def list_for_session(
        self, agent_id: str, parent_session_id: str
    ) -> list[DelegateState]:
        """All delegates belonging to a given agent+session pair."""
        return [
            d
            for d in self._delegates.values()
            if d.agent_id == agent_id and d.parent_session_id == parent_session_id
        ]

    def set_task_ref(self, delegate_id: str, task_ref: Any) -> None:
        """Attach an external task reference (e.g. a LangChain RunnableConfig)."""
        state = self._delegates.get(delegate_id)
        if state:
            state.task_ref = task_ref

    def mark_completed(self, delegate_id: str, result: dict[str, Any]) -> None:
        state = self._delegates.get(delegate_id)
        if not state:
            return
        state.status = "completed"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        state.result_summary = result.get("summary", "")
        state.steps_completed = result.get("steps", 0)
        state.tools_used = result.get("tools_used", [])
        state.token_usage = result.get("token_usage", {})
        self._persist_result(state, result)

    def mark_failed(self, delegate_id: str, error_message: str) -> None:
        state = self._delegates.get(delegate_id)
        if not state:
            return
        state.status = "failed"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        state.error_message = error_message
        self._persist_error(state, error_message)

    def mark_timeout(self, delegate_id: str) -> None:
        state = self._delegates.get(delegate_id)
        if not state:
            return
        state.status = "timeout"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        self._persist_error(
            state, f"Sub-agent exceeded timeout ({state.timeout_seconds}s)"
        )

    def check_max_per_session(
        self, agent_id: str, parent_session_id: str, max_count: int
    ) -> bool:
        """Return True if a new delegate can be spawned (still under max_count)."""
        active = [
            d
            for d in self._delegates.values()
            if d.agent_id == agent_id
            and d.parent_session_id == parent_session_id
            and d.status == "running"
        ]
        return len(active) < max_count

    # -- private helpers -------------------------------------------------------

    def _persist_result(self, state: DelegateState, result: dict[str, Any]) -> None:
        if not state.result_dir:
            return
        (state.result_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (state.result_dir / "result_summary.md").write_text(
            f"# Delegate Result: {state.role}\n\n"
            f"**Task:** {state.task}\n\n**Summary:**\n{state.result_summary}\n\n"
            f"**Steps:** {state.steps_completed}\n"
            f"**Tools:** {', '.join(state.tools_used)}\n"
            f"**Duration:** {state.duration_ms / 1000:.1f}s\n",
            encoding="utf-8",
        )

    def _persist_error(self, state: DelegateState, message: str) -> None:
        if not state.result_dir:
            return
        (state.result_dir / "error.json").write_text(
            json.dumps(
                {"error": message, "created_at": state.created_at},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (state.result_dir / "result_summary.md").write_text(
            f"# Delegate Failed: {state.role}\n\n"
            f"**Task:** {state.task}\n\n**Error:** {message}\n",
            encoding="utf-8",
        )
