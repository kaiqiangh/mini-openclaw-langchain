"""Tests for run replay API."""
import json
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api import replay
from api.errors import ApiError, error_payload
from tests.conftest import FakeAgentManager
from typing import cast


@pytest.fixture()
def client(tmp_path):
    workspace = tmp_path / "workspaces" / "default"
    workspace.mkdir(parents=True)
    audit_dir = workspace / "storage" / "audit"
    audit_dir.mkdir(parents=True)

    # Write sample runs.jsonl
    runs_file = audit_dir / "runs.jsonl"
    runs_file.write_text(json.dumps({
        "run_id": "run-123",
        "session_id": "sess-456",
        "trigger_type": "chat",
        "status": "ok",
        "duration_ms": 1000,
    }) + "\n")

    # Write sample tool_calls.jsonl
    tool_calls_file = audit_dir / "tool_calls.jsonl"
    tool_calls_file.write_text(json.dumps({
        "run_id": "run-123",
        "session_id": "sess-456",
        "tool_name": "web_search",
        "status": "ok",
    }) + "\n")

    # Minimal workspace structure
    (workspace / "workspace").mkdir()
    (workspace / "memory").mkdir()
    (workspace / "knowledge").mkdir()
    (workspace / "sessions").mkdir()
    (workspace / "storage" / "usage").mkdir()

    agent_manager = FakeAgentManager(tmp_path)
    typed_manager = cast("AgentManager", agent_manager)
    replay.set_agent_manager(typed_manager)

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def handler(_, exc):
        return JSONResponse(status_code=exc.status_code, content=error_payload(code=exc.code, message=exc.message))

    app.include_router(replay.router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c


def test_get_run_details(client):
    r = client.get("/api/v1/agents/default/runs/run-123")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["run"]["run_id"] == "run-123"
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["tool_name"] == "web_search"


def test_get_run_not_found(client):
    r = client.get("/api/v1/agents/default/runs/nonexistent")
    assert r.status_code == 404


def test_replay_nonexistent_run(client):
    r = client.post("/api/v1/agents/default/runs/nonexistent/replay")
    assert r.status_code == 404
