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
        self._hydrate_from_disk()

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
                    "delegate_id": delegate_id,
                    "agent_id": agent_id,
                    "parent_session_id": parent_session_id,
                    "task": task,
                    "role": role,
                    "allowed_tools": allowed_tools,
                    "blocked_tools": blocked_tools,
                    "timeout_seconds": timeout_seconds,
                    "sub_session_id": sub_session_id,
                    "created_at": state.created_at,
                    "status": state.status,
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
        state = self._delegates.get(delegate_id)
        if state is not None:
            return state
        self._hydrate_from_disk(delegate_id=delegate_id)
        return self._delegates.get(delegate_id)

    def list_for_session(
        self, agent_id: str, parent_session_id: str
    ) -> list[DelegateState]:
        """All delegates belonging to a given agent+session pair."""
        self._hydrate_from_disk(agent_id=agent_id, parent_session_id=parent_session_id)
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
        self._persist_config(state)

    def mark_failed(self, delegate_id: str, error_message: str) -> None:
        state = self._delegates.get(delegate_id)
        if not state:
            return
        state.status = "failed"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        state.error_message = error_message
        self._persist_error(state, error_message)
        self._persist_config(state)

    def mark_timeout(self, delegate_id: str) -> None:
        state = self._delegates.get(delegate_id)
        if not state:
            return
        state.status = "timeout"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        state.error_message = f"Sub-agent exceeded timeout ({state.timeout_seconds}s)"
        self._persist_error(
            state, state.error_message
        )
        self._persist_config(state)

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
                {
                    "error": message,
                    "created_at": state.created_at,
                    "status": state.status,
                    "completed_at": state.completed_at,
                    "duration_ms": state.duration_ms,
                },
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

    def _persist_config(self, state: DelegateState) -> None:
        if not state.result_dir:
            return
        (state.result_dir / "config.json").write_text(
            json.dumps(
                {
                    "delegate_id": state.delegate_id,
                    "agent_id": state.agent_id,
                    "parent_session_id": state.parent_session_id,
                    "sub_session_id": state.sub_session_id,
                    "task": state.task,
                    "role": state.role,
                    "allowed_tools": state.allowed_tools,
                    "blocked_tools": state.blocked_tools,
                    "timeout_seconds": state.timeout_seconds,
                    "created_at": state.created_at,
                    "completed_at": state.completed_at,
                    "duration_ms": state.duration_ms,
                    "status": state.status,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _mark_stale_timeout(self, state: DelegateState) -> None:
        state.status = "timeout"
        state.completed_at = time.time()
        state.duration_ms = int((state.completed_at - state.created_at) * 1000)
        timeout_seconds = state.timeout_seconds or 0
        state.error_message = f"Sub-agent exceeded timeout ({timeout_seconds}s)"
        self._persist_error(state, state.error_message)
        self._persist_config(state)

    def _hydrate_from_disk(
        self,
        *,
        delegate_id: str | None = None,
        agent_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        workspaces_dir = self.base_dir / "workspaces"
        if not workspaces_dir.exists():
            return

        pattern = "*/sessions/*/delegates/*/config.json"
        for config_path in workspaces_dir.glob(pattern):
            if not config_path.is_file():
                continue
            candidate_delegate_id = config_path.parent.name
            if delegate_id and candidate_delegate_id != delegate_id:
                continue
            if candidate_delegate_id in self._delegates:
                continue
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            candidate_agent_id = str(raw.get("agent_id", "")).strip()
            candidate_parent_session_id = str(
                raw.get("parent_session_id", "")
            ).strip()
            if agent_id and candidate_agent_id != agent_id:
                continue
            if parent_session_id and candidate_parent_session_id != parent_session_id:
                continue

            state = DelegateState(
                delegate_id=str(raw.get("delegate_id", candidate_delegate_id)).strip()
                or candidate_delegate_id,
                agent_id=candidate_agent_id or config_path.parents[4].name,
                parent_session_id=candidate_parent_session_id or config_path.parents[2].name,
                sub_session_id=str(raw.get("sub_session_id", "")).strip(),
                task=str(raw.get("task", "")).strip(),
                role=str(raw.get("role", "")).strip() or "delegate",
                allowed_tools=[
                    str(item).strip()
                    for item in raw.get("allowed_tools", [])
                    if str(item).strip()
                ],
                blocked_tools=[
                    str(item).strip()
                    for item in raw.get("blocked_tools", [])
                    if str(item).strip()
                ],
                timeout_seconds=(
                    int(raw["timeout_seconds"])
                    if raw.get("timeout_seconds") is not None
                    else None
                ),
                status=str(raw.get("status", "running")).strip() or "running",
                created_at=float(raw.get("created_at", time.time())),
                completed_at=(
                    float(raw["completed_at"])
                    if raw.get("completed_at") is not None
                    else None
                ),
                duration_ms=int(raw.get("duration_ms", 0)),
                result_dir=config_path.parent,
            )
            self._hydrate_terminal_files(state)
            if state.status == "running":
                timeout_seconds = state.timeout_seconds
                if (
                    timeout_seconds is not None
                    and timeout_seconds > 0
                    and (time.time() - state.created_at) >= timeout_seconds
                ):
                    self._mark_stale_timeout(state)
            self._delegates[state.delegate_id] = state

    def _hydrate_terminal_files(self, state: DelegateState) -> None:
        if not state.result_dir:
            return
        result_path = state.result_dir / "result.json"
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                result = {}
            if isinstance(result, dict):
                state.status = "completed"
                state.result_summary = str(result.get("summary", "")).strip() or None
                state.steps_completed = int(result.get("steps", 0))
                state.tools_used = [
                    str(item).strip()
                    for item in result.get("tools_used", [])
                    if str(item).strip()
                ]
                token_usage = result.get("token_usage", {})
                state.token_usage = token_usage if isinstance(token_usage, dict) else {}
        error_path = state.result_dir / "error.json"
        if error_path.exists():
            try:
                error_payload = json.loads(error_path.read_text(encoding="utf-8"))
            except Exception:
                error_payload = {}
            if isinstance(error_payload, dict):
                state.status = (
                    str(error_payload.get("status", state.status)).strip()
                    or state.status
                )
                state.error_message = str(error_payload.get("error", "")).strip() or None
                if error_payload.get("completed_at") is not None:
                    state.completed_at = float(error_payload["completed_at"])
                if error_payload.get("duration_ms") is not None:
                    state.duration_ms = int(error_payload["duration_ms"])
