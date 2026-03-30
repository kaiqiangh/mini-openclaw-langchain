"""Tests for approval API."""
import tempfile
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import approval
from api.errors import ApiError, error_payload
from fastapi import Request
from fastapi.responses import JSONResponse
from storage.approval_store import ApprovalStore, ApprovalStatus


@pytest.fixture()
def client(tmp_path):
    store = ApprovalStore(tmp_path)
    approval.set_dependencies(store)

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def handler(_, exc):
        return JSONResponse(status_code=exc.status_code, content=error_payload(code=exc.code, message=exc.message))

    app.include_router(approval.router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c, store


def test_list_empty_approvals(client):
    c, _ = client
    r = c.get("/api/v1/agents/default/approvals")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_create_and_approve(client):
    c, store = client
    req = store.create_request(
        agent_id="default", session_id="s1", run_id="r1",
        tool_name="terminal", tool_args={"command": "ls"}, trigger_type="chat",
    )
    r = c.get("/api/v1/agents/default/approvals")
    assert len(r.json()["data"]) == 1

    r = c.post(f"/api/v1/agents/default/approvals/{req.request_id}", json={"action": "approve"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"

    # Should not be pending anymore
    r = c.get("/api/v1/agents/default/approvals")
    assert len(r.json()["data"]) == 0


def test_deny_with_reason(client):
    c, store = client
    req = store.create_request(
        agent_id="default", session_id="s1", run_id="r1",
        tool_name="terminal", tool_args={}, trigger_type="chat",
    )
    r = c.post(f"/api/v1/agents/default/approvals/{req.request_id}", json={"action": "deny", "reason": "too risky"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "denied"


def test_double_resolve_rejected(client):
    c, store = client
    req = store.create_request(
        agent_id="default", session_id="s1", run_id="r1",
        tool_name="terminal", tool_args={}, trigger_type="chat",
    )
    c.post(f"/api/v1/agents/default/approvals/{req.request_id}", json={"action": "approve"})
    r = c.post(f"/api/v1/agents/default/approvals/{req.request_id}", json={"action": "deny"})
    assert r.status_code == 409
