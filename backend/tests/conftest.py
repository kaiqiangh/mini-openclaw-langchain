from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import (
    agents,
    chat,
    compress,
    config_api,
    files,
    scheduler_api,
    sessions,
    traces,
    tokens,
    usage,
)  # noqa: E402
from api.errors import ApiError, error_payload  # noqa: E402
from config import RuntimeConfig, load_runtime_config  # noqa: E402
from graph.memory_indexer import MemoryIndexer  # noqa: E402
from graph.session_manager import SessionManager  # noqa: E402
from scheduler.cron import CronScheduler  # noqa: E402
from scheduler.heartbeat import HeartbeatScheduler  # noqa: E402
from storage.run_store import AuditStore  # noqa: E402
from storage.usage_store import UsageStore  # noqa: E402

if TYPE_CHECKING:
    from graph.agent import AgentManager


@dataclass
class _Runtime:
    rag_mode: bool = False


@dataclass
class _Config:
    runtime: _Runtime = field(default_factory=_Runtime)


@dataclass
class FakeRuntime:
    agent_id: str
    root_dir: Path
    session_manager: SessionManager
    memory_indexer: MemoryIndexer
    usage_store: UsageStore
    audit_store: AuditStore
    runtime_config: RuntimeConfig


class FakeSessionRepository:
    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager
        self._messages: dict[tuple[bool, str], list[dict[str, object]]] = {}
        self._live_responses: dict[tuple[bool, str], dict[str, object]] = {}

    @staticmethod
    def _key(session_id: str, *, archived: bool) -> tuple[bool, str]:
        return archived, session_id

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @classmethod
    def _message_entry(
        cls,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, object]] | None = None,
        skill_uses: list[str] | None = None,
        selected_skills: list[str] | None = None,
    ) -> dict[str, object]:
        entry: dict[str, object] = {
            "role": role,
            "content": content,
            "timestamp_ms": cls._now_ms(),
        }
        if tool_calls:
            entry["tool_calls"] = list(tool_calls)
        if skill_uses:
            entry["skill_uses"] = list(dict.fromkeys(skill_uses))
        if selected_skills:
            entry["selected_skills"] = list(dict.fromkeys(selected_skills))
        return entry

    @staticmethod
    def _history_with_summary(
        messages: list[dict[str, object]],
        compressed_context: str,
    ) -> list[dict[str, object]]:
        merged = [dict(message) for message in messages]
        if not compressed_context.strip():
            return merged
        return [
            {
                "role": "assistant",
                "content": f"[Summary of Earlier Conversation]\n{compressed_context.strip()}",
            },
            *merged,
        ]

    @staticmethod
    def _with_live_response(
        messages: list[dict[str, object]],
        live_response: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        merged = [dict(message) for message in messages]
        if not isinstance(live_response, dict):
            return merged
        content = str(live_response.get("content", "")).strip()
        if not content:
            return merged
        merged.append(
            {
                "role": "assistant",
                "content": content,
                "streaming": True,
                "timestamp_ms": live_response.get("timestamp_ms", 0),
                "run_id": live_response.get("run_id", ""),
            }
        )
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
    ):
        _ = agent_id, graph_name
        session = (
            self.manager.load_session(session_id, archived=archived)
            if create_if_missing
            else self.manager.load_existing_session(session_id, archived=archived)
        )
        key = self._key(session_id, archived=archived)
        messages = [dict(item) for item in self._messages.get(key, [])]
        live_response = self._live_responses.get(key)
        if include_live and not archived:
            messages = self._with_live_response(messages, live_response)
        return SimpleNamespace(
            session_id=session_id,
            agent_id=agent_id,
            archived=archived,
            messages=messages,
            compressed_context=str(session.get("compressed_context", "")),
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
    ) -> list[dict[str, object]]:
        _ = agent_id, graph_name
        if create_if_missing:
            self.manager.load_session(session_id, archived=archived)
        key = self._key(session_id, archived=archived)
        session = self.manager.load_existing_session(session_id, archived=archived)
        messages = [dict(item) for item in self._messages.get(key, [])]
        return self._history_with_summary(messages, str(session.get("compressed_context", "")))

    async def delete_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
    ) -> bool:
        _ = agent_id
        key = self._key(session_id, archived=archived)
        self._messages.pop(key, None)
        self._live_responses.pop(key, None)
        return self.manager.delete_session(session_id, archived=archived)

    async def compress_history(
        self,
        *,
        agent_id: str,
        session_id: str,
        summary: str,
        n: int,
        graph_name: str = "default",
    ) -> dict[str, int]:
        _ = agent_id, graph_name
        key = self._key(session_id, archived=False)
        session = self.manager.load_session(session_id)
        messages = self._messages.get(key, [])
        archive_count = min(max(0, n), len(messages))
        to_archive = messages[:archive_count]
        remain = messages[archive_count:]

        if archive_count > 0:
            archive_path = self.manager.archive_dir / f"{session_id}_{int(time.time())}.json"
            self.manager._write_json_file(archive_path, to_archive)  # noqa: SLF001

        prior = str(session.get("compressed_context", "")).strip()
        normalized = summary.strip()
        if prior and normalized:
            session["compressed_context"] = f"{prior}\n---\n{normalized}"
        else:
            session["compressed_context"] = normalized or prior
        self.manager.save_session(session_id, session)
        self._messages[key] = list(remain)
        self._live_responses.pop(key, None)
        return {"archived_count": archive_count, "remaining_count": len(remain)}

    async def append_message(
        self,
        *,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, object]] | None = None,
        skill_uses: list[str] | None = None,
        selected_skills: list[str] | None = None,
    ) -> None:
        _ = agent_id
        self.manager.load_session(session_id)
        key = self._key(session_id, archived=False)
        rows = self._messages.setdefault(key, [])
        rows.append(
            self._message_entry(
                role,
                content,
                tool_calls=tool_calls,
                skill_uses=skill_uses,
                selected_skills=selected_skills,
            )
        )

    async def set_live_response(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        content: str,
    ) -> None:
        _ = agent_id
        self.manager.load_session(session_id)
        key = self._key(session_id, archived=False)
        self._live_responses[key] = {
            "run_id": run_id,
            "content": content,
            "timestamp_ms": self._now_ms(),
        }

    async def clear_live_response(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        _ = agent_id
        self._live_responses.pop(self._key(session_id, archived=False), None)


class FakeAgentManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config = _Config()
        self._runtimes: dict[str, FakeRuntime] = {}
        self._session_repositories: dict[str, FakeSessionRepository] = {}
        self.get_runtime("default")

    def _agent_root(self, agent_id: str) -> Path:
        return self.base_dir / "workspaces" / agent_id

    def _ensure_agent_root(self, agent_id: str) -> Path:
        root = self._agent_root(agent_id)
        for rel in [
            "workspace",
            "memory",
            "knowledge",
            "skills/get_weather",
            "sessions/archive",
            "sessions/archived_sessions",
            "storage",
        ]:
            (root / rel).mkdir(parents=True, exist_ok=True)
        if not (root / "workspace" / "SOUL.md").exists():
            (root / "workspace" / "SOUL.md").write_text("SOUL", encoding="utf-8")
            (root / "workspace" / "IDENTITY.md").write_text(
                "IDENTITY", encoding="utf-8"
            )
            (root / "workspace" / "USER.md").write_text("USER", encoding="utf-8")
            (root / "workspace" / "AGENTS.md").write_text("AGENTS", encoding="utf-8")
            (root / "workspace" / "HEARTBEAT.md").write_text(
                "HEARTBEAT", encoding="utf-8"
            )
            (root / "memory" / "MEMORY.md").write_text(
                "memory content", encoding="utf-8"
            )
            (root / "knowledge" / "note.md").write_text(
                "knowledge alpha beta", encoding="utf-8"
            )
            (root / "SKILLS_SNAPSHOT.md").write_text(
                "<available_skills></available_skills>\n", encoding="utf-8"
            )
        if not (root / "config.json").exists():
            (root / "config.json").write_text('{"rag_mode": false}\n', encoding="utf-8")
        return root

    def get_runtime(self, agent_id: str = "default") -> FakeRuntime:
        root = self._ensure_agent_root(agent_id)
        runtime_config = load_runtime_config(root / "config.json")
        runtime = self._runtimes.get(agent_id)
        if runtime is not None:
            runtime.runtime_config = runtime_config
            return runtime
        runtime = FakeRuntime(
            agent_id=agent_id,
            root_dir=root,
            session_manager=SessionManager(root),
            memory_indexer=MemoryIndexer(root),
            usage_store=UsageStore(root),
            audit_store=AuditStore(root),
            runtime_config=runtime_config,
        )
        runtime.audit_store.ensure_schema_descriptor()
        self._runtimes[agent_id] = runtime
        return runtime

    def get_agent_config_path(self, agent_id: str = "default") -> Path:
        root = self._ensure_agent_root(agent_id)
        return root / "config.json"

    def get_session_repository(self, agent_id: str = "default") -> FakeSessionRepository:
        runtime = self.get_runtime(agent_id)
        repository = self._session_repositories.get(agent_id)
        if repository is None:
            repository = FakeSessionRepository(runtime.session_manager)
            self._session_repositories[agent_id] = repository
        return repository

    @staticmethod
    def _llm_status() -> dict[str, object]:
        return {
            "valid": True,
            "runnable": True,
            "default_profile": "deepseek",
            "fallback_profiles": [],
            "warnings": [],
            "errors": [],
        }

    def list_agents(self) -> list[dict[str, object]]:
        rows = []
        for agent_id, runtime in self._runtimes.items():
            rows.append(
                {
                    "agent_id": agent_id,
                    "path": str(runtime.root_dir),
                    "created_at": 0.0,
                    "updated_at": 0.0,
                    "active_sessions": 0,
                    "archived_sessions": 0,
                    "llm_status": self._llm_status(),
                }
            )
        return rows

    def create_agent(self, agent_id: str) -> dict[str, object]:
        if agent_id in self._runtimes:
            raise ValueError(f"Agent already exists: {agent_id}")
        runtime = self.get_runtime(agent_id)
        return {
            "agent_id": runtime.agent_id,
            "path": str(runtime.root_dir),
            "created_at": 0.0,
            "updated_at": 0.0,
            "active_sessions": 0,
            "archived_sessions": 0,
            "llm_status": self._llm_status(),
        }

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id == "default":
            raise ValueError("Default agent cannot be deleted")
        runtime = self._runtimes.pop(agent_id, None)
        if runtime is None:
            return False
        return True

    def build_system_prompt(
        self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default"
    ) -> str:
        if rag_mode:
            return (
                f"SYSTEM PROMPT RAG=1 first={int(bool(is_first_turn))} agent={agent_id}\n"
                + ("MEMORY_CONTEXT " * 40)
            )
        return f"SYSTEM PROMPT RAG=0 first={int(bool(is_first_turn))} agent={agent_id}"

    async def generate_title(self, seed_text: str, agent_id: str = "default") -> str:
        _ = seed_text, agent_id
        return "Test Title"

    async def summarize_messages(
        self, messages: list[dict[str, object]], agent_id: str = "default"
    ) -> str:
        _ = messages, agent_id
        return "Compressed Summary"

    async def run_once(self, *, message: str, **kwargs):
        agent_id = str(kwargs.get("agent_id", "default"))
        repository = self.get_session_repository(agent_id)
        session_id = str(kwargs.get("session_id", ""))
        snapshot = await repository.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            include_live=False,
            create_if_missing=True,
        )
        if session_id and not bool(kwargs.get("resume_same_turn", False)):
            await repository.append_message(
                agent_id=agent_id,
                session_id=session_id,
                role="user",
                content=message,
            )
        text = f"RUN:first={int(len(snapshot.messages) == 0)}:{message[:40]}"
        if session_id:
            await repository.append_message(
                agent_id=agent_id,
                session_id=session_id,
                role="assistant",
                content=text,
            )
        return {"text": text}

    async def astream(self, message: str, session_id: str, **kwargs):
        agent_id = str(kwargs.get("agent_id", "default"))
        runtime = self.get_runtime(agent_id)
        repository = self.get_session_repository(agent_id)
        if not bool(kwargs.get("resume_same_turn", False)):
            await repository.append_message(
                agent_id=agent_id,
                session_id=session_id,
                role="user",
                content=message,
            )
            runtime.audit_store.append_message_link(
                run_id=None,
                session_id=session_id,
                role="user",
                segment_index=0,
                content=message,
                details={"source": "fake_chat_stream"},
            )
        yield {"type": "run_start", "data": {"run_id": "run-test", "attempt": 1}}
        yield {
            "type": "agent_update",
            "data": {
                "run_id": "run-test",
                "node": "model",
                "message_count": 1,
                "preview": "starting",
            },
        }
        yield {"type": "retrieval", "data": {"query": message, "results": []}}
        yield {"type": "token", "data": {"content": f"[{session_id}]A"}}
        yield {
            "type": "tool_start",
            "data": {"tool": "read_files", "input": {"path": "memory/MEMORY.md"}},
        }
        yield {"type": "tool_end", "data": {"tool": "read_files", "output": "ok"}}
        await repository.append_message(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=f"[{session_id}]A",
            tool_calls=[
                {
                    "tool": "read_files",
                    "input": {"path": "memory/MEMORY.md"},
                    "output": "ok",
                }
            ],
        )
        runtime.audit_store.append_message_link(
            run_id="run-test",
            session_id=session_id,
            role="assistant",
            segment_index=0,
            content=f"[{session_id}]A",
            details={"tool_call_count": 1},
        )
        yield {"type": "new_response", "data": {}}
        yield {
            "type": "reasoning",
            "data": {"run_id": "run-test", "content": "reasoning sample"},
        }
        yield {"type": "token", "data": {"content": "B"}}
        await repository.append_message(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content="B",
        )
        runtime.audit_store.append_message_link(
            run_id="run-test",
            session_id=session_id,
            role="assistant",
            segment_index=1,
            content="B",
            details={"tool_call_count": 0},
        )
        yield {
            "type": "done",
            "data": {
                "content": f"[{session_id}]AB",
                "session_id": session_id,
                "run_id": "run-test",
                "token_source": "messages",
            },
        }


@pytest.fixture()
def backend_base_dir(tmp_path: Path) -> Path:
    base = tmp_path
    for rel in [
        "workspace",
        "memory",
        "knowledge",
        "skills/get_weather",
        "sessions/archive",
        "sessions/archived_sessions",
        "storage",
        "workspaces",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    (base / "workspace" / "SOUL.md").write_text("SOUL", encoding="utf-8")
    (base / "workspace" / "IDENTITY.md").write_text("IDENTITY", encoding="utf-8")
    (base / "workspace" / "USER.md").write_text("USER", encoding="utf-8")
    (base / "workspace" / "AGENTS.md").write_text("AGENTS", encoding="utf-8")
    (base / "workspace" / "HEARTBEAT.md").write_text("HEARTBEAT", encoding="utf-8")
    (base / "memory" / "MEMORY.md").write_text("memory content", encoding="utf-8")
    (base / "knowledge" / "note.md").write_text(
        "knowledge alpha beta", encoding="utf-8"
    )
    (base / "SKILLS_SNAPSHOT.md").write_text(
        "<available_skills></available_skills>\n", encoding="utf-8"
    )

    (base / "config.json").write_text(
        json.dumps(
            {
                "rag_mode": False,
                "injection_mode": "every_turn",
                "bootstrap_max_chars": 20000,
                "bootstrap_total_max_chars": 150000,
                "tool_timeouts": {
                    "terminal_seconds": 30,
                    "python_repl_seconds": 30,
                    "fetch_url_seconds": 15,
                },
                "tool_output_limits": {
                    "terminal_chars": 5000,
                    "fetch_url_chars": 5000,
                    "read_file_chars": 10000,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    return base


@pytest.fixture()
def api_app(backend_base_dir: Path):
    app = FastAPI()

    agent_manager = FakeAgentManager(backend_base_dir)
    typed_agent_manager = cast("AgentManager", agent_manager)

    chat.set_agent_manager(typed_agent_manager)
    sessions.set_agent_manager(typed_agent_manager)
    files.set_dependencies(backend_base_dir, typed_agent_manager)
    tokens.set_dependencies(backend_base_dir, typed_agent_manager)
    compress.set_agent_manager(typed_agent_manager)
    config_api.set_dependencies(backend_base_dir, typed_agent_manager)
    usage.set_agent_manager(typed_agent_manager)
    agents.set_agent_manager(typed_agent_manager)
    traces.set_agent_manager(typed_agent_manager)
    runtime = agent_manager.get_runtime("default")
    heartbeat_scheduler = HeartbeatScheduler(
        base_dir=runtime.root_dir,
        config=runtime.runtime_config.heartbeat,
        agent_manager=typed_agent_manager,
        session_manager=runtime.session_manager,
        agent_id="default",
    )
    cron_scheduler = CronScheduler(
        base_dir=runtime.root_dir,
        config=runtime.runtime_config.cron,
        agent_manager=typed_agent_manager,
        session_manager=runtime.session_manager,
        agent_id="default",
    )
    scheduler_api.set_dependencies(
        backend_base_dir,
        typed_agent_manager,
        default_heartbeat_scheduler=heartbeat_scheduler,
        default_cron_scheduler=cron_scheduler,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code=exc.code, message=exc.message, details=exc.details
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(
                    str(part) for part in err.get("loc", []) if part != "body"
                ),
                "message": err.get("msg", "Invalid value"),
                "code": err.get("type", "validation_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(
                code="validation_error",
                message="Request validation failed",
                details={"items": details},
            ),
        )

    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(tokens.router, prefix="/api/v1")
    app.include_router(compress.router, prefix="/api/v1")
    app.include_router(config_api.router, prefix="/api/v1")
    app.include_router(usage.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(traces.router, prefix="/api/v1")
    app.include_router(scheduler_api.router, prefix="/api/v1")

    return {
        "app": app,
        "base_dir": backend_base_dir,
        "agent_manager": agent_manager,
        "heartbeat_scheduler": heartbeat_scheduler,
        "cron_scheduler": cron_scheduler,
    }


@pytest.fixture()
def client(api_app):
    with TestClient(api_app["app"]) as c:
        yield c
