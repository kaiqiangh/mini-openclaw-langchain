from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

from langchain_core.messages import BaseMessage

from graph.runtime_types import GraphRuntime, RuntimeEvent, RuntimeRequest, RuntimeResult
from graph.session_manager import SessionManager

from graph.runtime_types import RuntimeCheckpointer


class RuntimeWithSessionManager(Protocol):
    session_manager: SessionManager


_SKILL_PATH_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9._-])(?:\./)?skills/([A-Za-z0-9._-]+)(?=/)"
)


@dataclass(frozen=True)
class CheckpointSessionSnapshot:
    session_id: str
    agent_id: str
    archived: bool
    messages: list[dict[str, Any]]
    compressed_context: str
    live_response: dict[str, Any] | None = None


@dataclass
class _StreamAccumulator:
    agent_id: str
    session_id: str
    run_id: str = ""
    assistant_segments: list[dict[str, Any]] = field(default_factory=list)
    current_content: str = ""
    current_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    current_skill_uses: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    selected_skills_pending: bool = False
    last_live_sync_ms: int = 0
    completed_success: bool = False


class CheckpointSessionRepository:
    def __init__(
        self,
        *,
        runtime_getter: Callable[[str], RuntimeWithSessionManager],
        graph_getter: Callable[[str], GraphRuntime],
        checkpointer: RuntimeCheckpointer,
    ) -> None:
        self._runtime_getter = runtime_getter
        self._graph_getter = graph_getter
        self._checkpointer = checkpointer
        self._streams: dict[tuple[str, str], _StreamAccumulator] = {}

    def _runtime(self, agent_id: str) -> RuntimeWithSessionManager:
        return self._runtime_getter(agent_id)

    def _session_manager(self, agent_id: str) -> SessionManager:
        return self._runtime(agent_id).session_manager

    @staticmethod
    def _state_request(
        *,
        agent_id: str,
        session_id: str,
        graph_name: str = "default",
    ) -> RuntimeRequest:
        return RuntimeRequest(
            message="",
            history=[],
            session_id=session_id,
            agent_id=agent_id,
            graph_name=graph_name,
        )

    @staticmethod
    def _normalize_messages(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        messages: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                messages.append(dict(item))
        return messages

    @staticmethod
    def _normalize_live_response(value: Any) -> dict[str, Any] | None:
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _error_code(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("code", "")).strip()
        return str(getattr(value, "code", "")).strip()

    @staticmethod
    def _has_broken_tool_loop(model_messages: Any) -> bool:
        if not isinstance(model_messages, list) or not model_messages:
            return False
        saw_tool_call = False
        saw_tool_result = False
        for message in model_messages:
            if not isinstance(message, BaseMessage):
                continue
            tool_calls = getattr(message, "tool_calls", None)
            if isinstance(tool_calls, list) and tool_calls:
                saw_tool_call = True
            if getattr(message, "tool_call_id", None):
                saw_tool_result = True
        return saw_tool_call and saw_tool_result

    @classmethod
    def _needs_runtime_repair(cls, state: dict[str, Any]) -> bool:
        if cls._error_code(state.get("error")) != "max_steps_reached":
            return False
        if str(state.get("final_text", "")).strip():
            return False
        if not str(state.get("fallback_final_text", "")).strip():
            return False
        messages = cls._normalize_messages(state.get("messages", []))
        if not messages:
            return False
        last = messages[-1]
        if str(last.get("role", "")).strip().lower() != "user":
            return False
        return cls._has_broken_tool_loop(state.get("model_messages", []))

    @staticmethod
    def _runtime_repair_values() -> dict[str, Any]:
        return {
            "run_id": "",
            "candidate_index": 0,
            "retry_index": 0,
            "attempt_number": 0,
            "loop_count": 0,
            "active_model": "",
            "input_messages": [],
            "model_messages": [],
            "pending_tool_calls": [],
            "pending_new_response": False,
            "token_source": None,
            "latest_model_snapshot": "",
            "fallback_final_text": "",
            "final_text": "",
            "live_response": None,
            "assistant_segments": [],
            "selected_skill_names": [],
            "tool_history": [],
            "usage_payload": {},
            "usage_signature": "",
            "usage_sources": {},
            "structured_response": None,
            "error": None,
        }

    async def get_state(
        self,
        *,
        agent_id: str,
        session_id: str,
        graph_name: str = "default",
    ) -> dict[str, Any]:
        request = self._state_request(
            agent_id=agent_id, session_id=session_id, graph_name=graph_name
        )
        return await self._graph_getter(graph_name).aget_state(request)

    async def get_state_history(
        self,
        *,
        agent_id: str,
        session_id: str,
        graph_name: str = "default",
    ) -> list[dict[str, Any]]:
        request = self._state_request(
            agent_id=agent_id, session_id=session_id, graph_name=graph_name
        )
        return await self._graph_getter(graph_name).aget_state_history(request)

    async def update_state(
        self,
        *,
        agent_id: str,
        session_id: str,
        values: dict[str, Any],
        graph_name: str = "default",
    ) -> dict[str, Any]:
        request = self._state_request(
            agent_id=agent_id, session_id=session_id, graph_name=graph_name
        )
        return await self._graph_getter(graph_name).aupdate_state(request, values)

    async def _ensure_session_state(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
        create_if_missing: bool = False,
        graph_name: str = "default",
    ) -> dict[str, Any]:
        session_manager = self._session_manager(agent_id)
        session = (
            await session_manager.load_session(session_id, archived=archived)
            if create_if_missing
            else await session_manager.load_existing_session(session_id, archived=archived)
        )

        state = await self.get_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )
        compressed_context = str(session.get("compressed_context", "")).strip()
        state_updated = False
        if compressed_context != str(state.get("compressed_context", "")).strip():
            await self.update_state(
                agent_id=agent_id,
                session_id=session_id,
                values={"compressed_context": compressed_context},
                graph_name=graph_name,
            )
            state_updated = True

        if state_updated:
            state = await self.get_state(
                agent_id=agent_id,
                session_id=session_id,
                graph_name=graph_name,
            )

        if not archived and self._needs_runtime_repair(state):
            await self.update_state(
                agent_id=agent_id,
                session_id=session_id,
                values=self._runtime_repair_values(),
                graph_name=graph_name,
            )

        return session

    @staticmethod
    def _message_entry(
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        skill_uses: list[str] | None = None,
        selected_skills: list[str] | None = None,
        timestamp_ms: int | None = None,
        event_kind: str | None = None,
        delegate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp_ms": timestamp_ms or int(time.time() * 1000),
        }
        if tool_calls:
            entry["tool_calls"] = list(tool_calls)
        if skill_uses:
            entry["skill_uses"] = list(dict.fromkeys(skill_uses))
        if selected_skills:
            entry["selected_skills"] = list(dict.fromkeys(selected_skills))
        if event_kind:
            entry["event_kind"] = event_kind
        if delegate:
            entry["delegate"] = dict(delegate)
        return entry

    @staticmethod
    def _merge_assistant_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for msg in messages:
            if (
                merged
                and msg.get("role") == "assistant"
                and merged[-1].get("role") == "assistant"
            ):
                merged[-1]["content"] = (
                    str(merged[-1].get("content", ""))
                    + "\n"
                    + str(msg.get("content", ""))
                ).strip()
                continue
            merged.append(dict(msg))
        return merged

    @staticmethod
    def _history_with_summary(
        messages: list[dict[str, Any]],
        compressed_context: str,
    ) -> list[dict[str, Any]]:
        merged = CheckpointSessionRepository._merge_assistant_messages(messages)
        normalized_summary = compressed_context.strip()
        if not normalized_summary:
            return merged
        return [
            {
                "role": "assistant",
                "content": f"[Summary of Earlier Conversation]\n{normalized_summary}",
            },
            *merged,
        ]

    @staticmethod
    def _merge_live_response(
        messages: list[dict[str, Any]],
        live_response: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        merged = [dict(message) for message in messages]
        if live_response is None:
            return merged
        content = str(live_response.get("content", "")).strip()
        tool_calls = live_response.get("tool_calls")
        skill_uses = live_response.get("skill_uses")
        selected_skills = live_response.get("selected_skills")
        if (
            not content
            and not (isinstance(tool_calls, list) and tool_calls)
            and not (isinstance(skill_uses, list) and skill_uses)
            and not (isinstance(selected_skills, list) and selected_skills)
        ):
            return merged
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "streaming": True,
        }
        timestamp_ms = live_response.get("timestamp_ms")
        if timestamp_ms is not None:
            entry["timestamp_ms"] = timestamp_ms
        if isinstance(tool_calls, list) and tool_calls:
            entry["tool_calls"] = list(tool_calls)
        if isinstance(skill_uses, list) and skill_uses:
            entry["skill_uses"] = list(dict.fromkeys(str(item) for item in skill_uses))
        if isinstance(selected_skills, list) and selected_skills:
            entry["selected_skills"] = list(
                dict.fromkeys(str(item) for item in selected_skills)
            )
        run_id = str(live_response.get("run_id", "")).strip()
        if run_id:
            entry["run_id"] = run_id
        merged.append(entry)
        return merged

    async def load_snapshot(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
        include_live: bool = True,
        create_if_missing: bool = False,
        graph_name: str = "default",
    ) -> CheckpointSessionSnapshot:
        session = await self._ensure_session_state(
            agent_id=agent_id,
            session_id=session_id,
            archived=archived,
            create_if_missing=create_if_missing,
            graph_name=graph_name,
        )
        state = await self.get_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )
        messages = self._normalize_messages(state.get("messages", []))
        live_response = (
            self._normalize_live_response(state.get("live_response"))
            if include_live and not archived
            else None
        )
        compressed_context = str(session.get("compressed_context", "")).strip() or str(
            state.get("compressed_context", "")
        ).strip()
        merged_messages = self._merge_live_response(messages, live_response)
        return CheckpointSessionSnapshot(
            session_id=session_id,
            agent_id=agent_id,
            archived=archived,
            messages=merged_messages,
            compressed_context=compressed_context,
            live_response=live_response,
        )

    async def load_history_for_agent(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
        create_if_missing: bool = False,
        graph_name: str = "default",
    ) -> list[dict[str, Any]]:
        snapshot = await self.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            archived=archived,
            include_live=False,
            create_if_missing=create_if_missing,
            graph_name=graph_name,
        )
        return self._history_with_summary(snapshot.messages, snapshot.compressed_context)

    async def prepare_runtime_request(self, request: RuntimeRequest) -> RuntimeRequest:
        session = await self._ensure_session_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            create_if_missing=True,
            graph_name=request.graph_name,
        )
        compressed_context = str(session.get("compressed_context", "")).strip()
        state = await self.get_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
        )
        messages = self._normalize_messages(state.get("messages", []))
        is_first_turn = len(messages) == 0
        normalized_message = request.message.strip()

        key = (request.agent_id, request.session_id)
        self._streams.pop(key, None)

        if request.resume_same_turn and messages:
            last = messages[-1]
            if (
                str(last.get("role", "")).strip() == "user"
                and str(last.get("content", "")).strip() == normalized_message
            ):
                await self.update_state(
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    graph_name=request.graph_name,
                    values={
                        "live_response": None,
                        "assistant_segments": [],
                        "selected_skill_names": [],
                    },
                )
                history = self._history_with_summary(messages[:-1], compressed_context)
                return replace(
                    request,
                    history=history,
                    is_first_turn=is_first_turn,
                    resume_same_turn=True,
                )

        user_entry = self._message_entry("user", request.message)
        updated_messages = [*messages, user_entry]
        await self.update_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
            values={
                "messages": updated_messages,
                "compressed_context": compressed_context,
                "live_response": None,
                "assistant_segments": [],
                "selected_skill_names": [],
            },
        )
        history = self._history_with_summary(messages, compressed_context)
        return replace(request, history=history, is_first_turn=is_first_turn)

    @staticmethod
    def _merge_unique_names(existing: list[str], additions: list[str]) -> list[str]:
        if not additions:
            return existing
        seen = {item for item in existing if item}
        merged = list(existing)
        for item in additions:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)
        return merged

    @staticmethod
    def _extract_skill_uses(value: Any) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        def visit(node: Any) -> None:
            if isinstance(node, str):
                for match in _SKILL_PATH_PATTERN.finditer(node):
                    skill_name = str(match.group(1)).strip()
                    if not skill_name or skill_name in seen:
                        continue
                    seen.add(skill_name)
                    found.append(skill_name)
                return
            if isinstance(node, dict):
                for child in node.values():
                    visit(child)
                return
            if isinstance(node, (list, tuple, set)):
                for child in node:
                    visit(child)

        visit(value)
        return found

    @staticmethod
    def _snapshot_live_content(state: _StreamAccumulator) -> str:
        content_parts: list[str] = []
        for segment in state.assistant_segments:
            text = str(segment.get("content", "")).strip()
            if text:
                content_parts.append(text)
        current = state.current_content.strip()
        if current:
            content_parts.append(current)
        return "\n\n".join(content_parts).strip()

    @staticmethod
    def _flush_current_segment(
        state: _StreamAccumulator, fallback_content: str = ""
    ) -> None:
        content = state.current_content.strip() or fallback_content.strip()
        if content or state.current_tool_calls or state.current_skill_uses:
            segment = {
                "content": content,
                "tool_calls": list(state.current_tool_calls),
                "skill_uses": list(state.current_skill_uses),
            }
            if state.selected_skills_pending and state.selected_skills:
                segment["selected_skills"] = list(state.selected_skills)
                state.selected_skills_pending = False
            state.assistant_segments.append(segment)
        state.current_content = ""
        state.current_tool_calls = []
        state.current_skill_uses = []

    async def _persist_live_snapshot(
        self,
        request: RuntimeRequest,
        state: _StreamAccumulator,
        *,
        force: bool = False,
    ) -> None:
        now_ms = int(time.time() * 1000)
        if not force and now_ms - state.last_live_sync_ms < 350:
            return

        content = self._snapshot_live_content(state)
        tool_calls = list(state.current_tool_calls)
        skill_uses = list(state.current_skill_uses)
        selected_skills = list(state.selected_skills)
        if not content and not tool_calls and not skill_uses and not selected_skills:
            return

        live_response = {
            "run_id": state.run_id or "__pending__",
            "content": content,
            "timestamp_ms": now_ms,
        }
        if tool_calls:
            live_response["tool_calls"] = tool_calls
        if skill_uses:
            live_response["skill_uses"] = list(dict.fromkeys(skill_uses))
        if selected_skills:
            live_response["selected_skills"] = list(dict.fromkeys(selected_skills))
        await self.update_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
            values={
                "live_response": live_response,
                "assistant_segments": list(state.assistant_segments),
                "selected_skill_names": list(selected_skills),
            },
        )
        state.last_live_sync_ms = now_ms

    async def apply_stream_event(
        self, request: RuntimeRequest, event: RuntimeEvent
    ) -> None:
        key = (request.agent_id, request.session_id)
        state = self._streams.setdefault(
            key,
            _StreamAccumulator(
                agent_id=request.agent_id,
                session_id=request.session_id,
            ),
        )
        data = event.data

        if event.type == "run_start":
            run_id = str(data.get("run_id", "")).strip()
            if run_id:
                state.run_id = run_id
                await self._persist_live_snapshot(request, state, force=True)
            return

        if event.type == "selected_skills":
            payload_skills = data.get("skills", [])
            selected_names: list[str] = []
            if isinstance(payload_skills, list):
                for item in payload_skills:
                    if isinstance(item, dict):
                        name = str(item.get("name", "")).strip()
                    else:
                        name = str(item).strip()
                    if name:
                        selected_names.append(name)
            state.selected_skills = self._merge_unique_names([], selected_names)
            state.selected_skills_pending = bool(state.selected_skills)
            await self._persist_live_snapshot(request, state, force=True)
            return

        if event.type == "token":
            state.current_content += str(data.get("content", ""))
            await self._persist_live_snapshot(request, state, force=False)
            return

        if event.type == "tool_start":
            skill_uses = self._extract_skill_uses(data.get("input", {}))
            state.current_skill_uses = self._merge_unique_names(
                state.current_skill_uses,
                skill_uses,
            )
            state.current_tool_calls.append(
                {
                    "tool": data.get("tool", "tool"),
                    "input": data.get("input", {}),
                }
            )
            await self._persist_live_snapshot(request, state, force=True)
            return

        if event.type == "tool_end" and state.current_tool_calls:
            state.current_tool_calls[-1]["output"] = data.get("output", "")
            await self._persist_live_snapshot(request, state, force=True)
            return

        if event.type == "new_response":
            self._flush_current_segment(state)
            await self._persist_live_snapshot(request, state, force=True)
            return

        if event.type == "done":
            done_content = str(data.get("content", "")).strip()
            self._flush_current_segment(state, fallback_content=done_content)
            state.completed_success = True
            return

        if event.type == "error":
            state.completed_success = False

    async def finalize_stream(self, request: RuntimeRequest) -> None:
        key = (request.agent_id, request.session_id)
        state = self._streams.pop(key, None)
        if state is None:
            return

        updates: dict[str, Any] = {
            "live_response": None,
            "assistant_segments": [],
        }
        if state.completed_success:
            state_values = await self.get_state(
                agent_id=request.agent_id,
                session_id=request.session_id,
                graph_name=request.graph_name,
            )
            messages = self._normalize_messages(state_values.get("messages", []))
            new_entries = [
                self._message_entry(
                    "assistant",
                    str(segment.get("content", "")),
                    tool_calls=(
                        segment.get("tool_calls")
                        if isinstance(segment.get("tool_calls"), list)
                        else None
                    ),
                    skill_uses=(
                        segment.get("skill_uses")
                        if isinstance(segment.get("skill_uses"), list)
                        else None
                    ),
                    selected_skills=(
                        segment.get("selected_skills")
                        if isinstance(segment.get("selected_skills"), list)
                        else None
                    ),
                )
                for segment in state.assistant_segments
                if str(segment.get("content", "")).strip()
                or segment.get("tool_calls")
                or segment.get("skill_uses")
            ]
            updates["messages"] = [*messages, *new_entries]
            updates["selected_skill_names"] = list(state.selected_skills)
        else:
            updates["selected_skill_names"] = []

        await self.update_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
            values=updates,
        )

    async def fail_stream(self, request: RuntimeRequest) -> None:
        key = (request.agent_id, request.session_id)
        self._streams.pop(key, None)
        await self.update_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
            values={
                "live_response": None,
                "assistant_segments": [],
                "selected_skill_names": [],
            },
        )

    @staticmethod
    def _tool_details_from_messages(
        messages: list[BaseMessage],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        tool_calls: list[dict[str, Any]] = []
        skill_uses: list[str] = []
        seen_skills: set[str] = set()
        for message in messages:
            message_tool_calls = getattr(message, "tool_calls", None)
            if not isinstance(message_tool_calls, list):
                continue
            for call in message_tool_calls:
                if not isinstance(call, dict):
                    continue
                args = call.get("args", {})
                tool_calls.append(
                    {
                        "tool": call.get("name", "tool"),
                        "input": args,
                    }
                )
                for skill in CheckpointSessionRepository._extract_skill_uses(args):
                    if skill in seen_skills:
                        continue
                    seen_skills.add(skill)
                    skill_uses.append(skill)
        return tool_calls, skill_uses

    async def persist_invoke_result(
        self,
        request: RuntimeRequest,
        result: RuntimeResult,
    ) -> None:
        state_values = await self.get_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
        )
        messages = self._normalize_messages(state_values.get("messages", []))
        tool_calls, skill_uses = self._tool_details_from_messages(result.messages)
        assistant_entry = self._message_entry(
            "assistant",
            result.text,
            tool_calls=tool_calls or None,
            skill_uses=skill_uses or None,
            selected_skills=result.selected_skills or None,
        )
        await self.update_state(
            agent_id=request.agent_id,
            session_id=request.session_id,
            graph_name=request.graph_name,
            values={
                "messages": [*messages, assistant_entry],
                "live_response": None,
                "assistant_segments": [],
                "selected_skill_names": list(result.selected_skills),
            },
        )

    async def append_message(
        self,
        *,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        skill_uses: list[str] | None = None,
        selected_skills: list[str] | None = None,
        timestamp_ms: int | None = None,
        event_kind: str | None = None,
        delegate: dict[str, Any] | None = None,
        graph_name: str = "default",
    ) -> None:
        await self._ensure_session_state(
            agent_id=agent_id,
            session_id=session_id,
            create_if_missing=True,
            graph_name=graph_name,
        )
        state = await self.get_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )
        messages = self._normalize_messages(state.get("messages", []))
        messages.append(
            self._message_entry(
                role,
                content,
                tool_calls=tool_calls,
                skill_uses=skill_uses,
                selected_skills=selected_skills,
                timestamp_ms=timestamp_ms,
                event_kind=event_kind,
                delegate=delegate,
            )
        )
        await self.update_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
            values={"messages": messages},
        )

    async def compress_history(
        self,
        *,
        agent_id: str,
        session_id: str,
        summary: str,
        n: int,
        graph_name: str = "default",
    ) -> dict[str, int]:
        session_manager = self._session_manager(agent_id)
        await self._ensure_session_state(
            agent_id=agent_id,
            session_id=session_id,
            create_if_missing=False,
            graph_name=graph_name,
        )
        state = await self.get_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )
        messages = self._normalize_messages(state.get("messages", []))
        archive_count = min(max(0, n), len(messages))
        to_archive = messages[:archive_count]
        remain = messages[archive_count:]

        if archive_count > 0:
            archive_path = (
                session_manager.archive_dir / f"{session_id}_{int(time.time())}.json"
            )
            session_manager._write_json_file(archive_path, to_archive)  # noqa: SLF001

        session = await session_manager.load_session(session_id)
        prior = str(session.get("compressed_context", "")).strip()
        normalized = summary.strip()
        if prior and normalized:
            session["compressed_context"] = f"{prior}\n---\n{normalized}"
        else:
            session["compressed_context"] = normalized or prior
        await session_manager.save_session(session_id, session)
        compressed_context = str(session.get("compressed_context", "")).strip()
        await self.update_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
            values={
                "messages": remain,
                "compressed_context": compressed_context,
                "live_response": None,
                "assistant_segments": [],
            },
        )
        return {"archived_count": archive_count, "remaining_count": len(remain)}

    async def delete_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
    ) -> bool:
        deleted = await self._session_manager(agent_id).delete_session(
            session_id, archived=archived
        )
        if deleted:
            await self._checkpointer.delete_thread(agent_id=agent_id, thread_id=session_id)
        return deleted
