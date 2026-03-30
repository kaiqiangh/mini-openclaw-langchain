"""Tests for setup API."""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import setup
from api.errors import ApiError, error_payload
from fastapi import Request
from fastapi.responses import JSONResponse


@pytest.fixture()
def client(tmp_path):
    os.environ.pop("APP_ADMIN_TOKEN", None)
    os.environ.pop("DEEPSEEK_API_KEY", None)

    setup.set_base_dir(tmp_path)

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def handler(_, exc):
        return JSONResponse(status_code=exc.status_code, content=error_payload(code=exc.code, message=exc.message))

    app.include_router(setup.router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c, tmp_path


def test_setup_status_needs_setup(client):
    c, _ = client
    r = c.get("/api/v1/setup/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["needs_setup"] is True
    assert data["admin_token_configured"] is False


def test_configure_system_deepseek(client):
    c, tmp_path = client
    r = c.post("/api/v1/setup/configure", json={
        "admin_token": "test-token-1234",
        "llm_provider": "deepseek",
        "llm_api_key": "sk-test-key",
    })
    assert r.status_code == 200
    assert r.json()["data"]["configured"] is True

    env_content = (tmp_path / ".env").read_text()
    assert "APP_ADMIN_TOKEN=test-token-1234" in env_content
    assert "DEEPSEEK_API_KEY=sk-test-key" in env_content


def test_configure_system_openai(client):
    c, tmp_path = client
    r = c.post("/api/v1/setup/configure", json={
        "admin_token": "test-token-1234",
        "llm_provider": "openai",
        "llm_api_key": "sk-openai-key",
    })
    assert r.status_code == 200
    assert r.json()["data"]["llm_provider"] == "openai"

    env_content = (tmp_path / ".env").read_text()
    assert "OPENAI_API_KEY=sk-openai-key" in env_content


def test_configure_rejects_short_token(client):
    c, _ = client
    r = c.post("/api/v1/setup/configure", json={
        "admin_token": "short",
        "llm_provider": "deepseek",
        "llm_api_key": "sk-test",
    })
    assert r.status_code == 422


def test_configure_rejects_unknown_provider(client):
    c, _ = client
    r = c.post("/api/v1/setup/configure", json={
        "admin_token": "test-token-1234",
        "llm_provider": "unknown_provider",
        "llm_api_key": "sk-test",
    })
    assert r.status_code == 422
