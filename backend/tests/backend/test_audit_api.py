"""Tests for audit browsing API."""
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def client_with_audit(tmp_path):
    """Create a test client with sample audit data."""
    import sys
    BACKEND_DIR = Path(__file__).resolve().parents[1]
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from api import agents, audit, chat, sessions, scheduler_api
    from api.errors import ApiError, error_payload
    from config import RuntimeConfig
    from graph.memory_indexer import MemoryIndexer
    from graph.session_manager import SessionManager
    from scheduler.cron import CronScheduler
    from scheduler.heartbeat import HeartbeatScheduler
    from storage.run_store import AuditStore
    from storage.usage_store import UsageStore
    from tests.conftest import FakeAgentManager
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from typing import cast

    # Setup workspace with audit data
    workspace = tmp_path / "workspaces" / "default"
    workspace.mkdir(parents=True)
    audit_dir = workspace / "storage" / "audit"
    audit_dir.mkdir(parents=True)

    # Write sample tool_calls.jsonl
    tool_calls_file = audit_dir / "tool_calls.jsonl"
    entries = [
        {"run_id": "run-1", "session_id": "sess-1", "trigger_type": "chat", "tool_name": "web_search", "status": "ok", "duration_ms": 500, "timestamp": 1711800000},
        {"run_id": "run-2", "session_id": "sess-2", "trigger_type": "chat", "tool_name": "fetch_url", "status": "error", "duration_ms": 200, "timestamp": 1711800100},
        {"run_id": "run-3", "session_id": "sess-1", "trigger_type": "cron", "tool_name": "web_search", "status": "ok", "duration_ms": 300, "timestamp": 1711800200},
    ]
    tool_calls_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    # Write sample runs.jsonl
    runs_file = audit_dir / "runs.jsonl"
    runs = [
        {"run_id": "run-1", "session_id": "sess-1", "trigger_type": "chat", "status": "ok", "duration_ms": 1000},
        {"run_id": "run-2", "session_id": "sess-2", "trigger_type": "chat", "status": "error", "duration_ms": 500},
    ]
    runs_file.write_text("\n".join(json.dumps(r) for r in runs) + "\n")

    # Setup minimal workspace structure
    (workspace / "workspace").mkdir()
    (workspace / "memory").mkdir()
    (workspace / "knowledge").mkdir()
    (workspace / "sessions").mkdir()
    (workspace / "storage" / "usage").mkdir()

    # Create FakeAgentManager
    agent_manager = FakeAgentManager(tmp_path)
    typed_manager = cast("AgentManager", agent_manager)

    audit.set_agent_manager(typed_manager)

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=exc.code, message=exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=error_payload(code="validation_error", message="Validation failed"))

    app.include_router(audit.router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c


def test_list_tool_calls(client_with_audit):
    """Audit API must list recent tool calls for an agent."""
    response = client_with_audit.get("/api/v1/agents/default/audit/tool-calls?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) == 3


def test_list_tool_calls_filter_by_tool_name(client_with_audit):
    """Audit API must filter tool calls by tool_name."""
    response = client_with_audit.get("/api/v1/agents/default/audit/tool-calls?tool_name=web_search")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert all(e["tool_name"] == "web_search" for e in data["data"])


def test_list_tool_calls_filter_by_status(client_with_audit):
    """Audit API must filter tool calls by status."""
    response = client_with_audit.get("/api/v1/agents/default/audit/tool-calls?status=error")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["status"] == "error"


def test_list_runs(client_with_audit):
    """Audit API must list recent runs for an agent."""
    response = client_with_audit.get("/api/v1/agents/default/audit/runs?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) == 2
