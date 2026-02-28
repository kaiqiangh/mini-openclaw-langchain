from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import agents, chat, compress, config_api, files, sessions, tokens, usage  # noqa: E402
from api.errors import ApiError, error_payload  # noqa: E402
from config import RuntimeConfig, load_runtime_config  # noqa: E402
from graph.memory_indexer import MemoryIndexer  # noqa: E402
from graph.session_manager import SessionManager  # noqa: E402
from storage.run_store import AuditStore  # noqa: E402
from storage.usage_store import UsageStore  # noqa: E402


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


class FakeAgentManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config = _Config()
        self._runtimes: dict[str, FakeRuntime] = {}
        runtime = self.get_runtime("default")
        self.session_manager = runtime.session_manager
        self.memory_indexer = runtime.memory_indexer
        self.audit_store = runtime.audit_store
        self.usage_store = runtime.usage_store

    def _agent_root(self, agent_id: str) -> Path:
        if agent_id == "default":
            return self.base_dir
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
            (root / "workspace" / "IDENTITY.md").write_text("IDENTITY", encoding="utf-8")
            (root / "workspace" / "USER.md").write_text("USER", encoding="utf-8")
            (root / "workspace" / "AGENTS.md").write_text("AGENTS", encoding="utf-8")
            (root / "workspace" / "HEARTBEAT.md").write_text("HEARTBEAT", encoding="utf-8")
            (root / "memory" / "MEMORY.md").write_text("memory content", encoding="utf-8")
            (root / "knowledge" / "note.md").write_text("knowledge alpha beta", encoding="utf-8")
            (root / "SKILLS_SNAPSHOT.md").write_text("<available_skills></available_skills>\n", encoding="utf-8")
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

    def get_session_manager(self, agent_id: str = "default") -> SessionManager:
        return self.get_runtime(agent_id).session_manager

    def get_memory_indexer(self, agent_id: str = "default") -> MemoryIndexer:
        return self.get_runtime(agent_id).memory_indexer

    def get_usage_store(self, agent_id: str = "default") -> UsageStore:
        return self.get_runtime(agent_id).usage_store

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
        }

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id == "default":
            raise ValueError("Default agent cannot be deleted")
        runtime = self._runtimes.pop(agent_id, None)
        if runtime is None:
            return False
        return True

    def build_system_prompt(self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default") -> str:
        _ = rag_mode, is_first_turn, agent_id
        return "SYSTEM PROMPT"

    async def generate_title(self, seed_text: str, agent_id: str = "default") -> str:
        _ = seed_text, agent_id
        return "Test Title"

    async def summarize_messages(self, messages: list[dict[str, object]], agent_id: str = "default") -> str:
        _ = messages, agent_id
        return "Compressed Summary"

    async def run_once(self, *, message: str, **kwargs):
        _ = kwargs
        return {"text": f"RUN:{message[:40]}"}

    async def astream(self, message: str, history: list[dict[str, object]], session_id: str, **kwargs):
        _ = history, kwargs
        yield {"type": "run_start", "data": {"run_id": "run-test", "attempt": 1}}
        yield {
            "type": "agent_update",
            "data": {"run_id": "run-test", "node": "model", "message_count": 1, "preview": "starting"},
        }
        yield {"type": "retrieval", "data": {"query": message, "results": []}}
        yield {"type": "token", "data": {"content": f"[{session_id}]A"}}
        yield {"type": "tool_start", "data": {"tool": "read_file", "input": {"path": "memory/MEMORY.md"}}}
        yield {"type": "tool_end", "data": {"tool": "read_file", "output": "ok"}}
        yield {"type": "new_response", "data": {}}
        yield {"type": "reasoning", "data": {"run_id": "run-test", "content": "reasoning sample"}}
        yield {"type": "token", "data": {"content": "B"}}
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
    (base / "knowledge" / "note.md").write_text("knowledge alpha beta", encoding="utf-8")
    (base / "SKILLS_SNAPSHOT.md").write_text("<available_skills></available_skills>\n", encoding="utf-8")

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
    session_manager = agent_manager.get_session_manager("default")

    chat.set_agent_manager(agent_manager)
    sessions.set_agent_manager(agent_manager)
    files.set_dependencies(backend_base_dir, agent_manager)
    tokens.set_dependencies(backend_base_dir, agent_manager)
    compress.set_agent_manager(agent_manager)
    config_api.set_dependencies(backend_base_dir, agent_manager)
    usage.set_agent_manager(agent_manager)
    agents.set_agent_manager(agent_manager)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=exc.code, message=exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in err.get("loc", []) if part != "body"),
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

    app.include_router(chat.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(tokens.router, prefix="/api")
    app.include_router(compress.router, prefix="/api")
    app.include_router(config_api.router, prefix="/api")
    app.include_router(usage.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")

    return {
        "app": app,
        "base_dir": backend_base_dir,
        "session_manager": session_manager,
        "agent_manager": agent_manager,
        "memory_indexer": agent_manager.get_memory_indexer("default"),
    }


@pytest.fixture()
def client(api_app):
    with TestClient(api_app["app"]) as c:
        yield c
