"""Tests for setup API."""
import asyncio
import os
import stat
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
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600

    (tmp_path / ".env").chmod(0o644)
    rejected = c.post("/api/v1/setup/configure", json={
        "admin_token": "test-token-1234",
        "llm_provider": "deepseek",
        "llm_api_key": "sk-test-key-2",
    })
    assert rejected.status_code == 401
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o644


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


def test_configure_rechecks_bootstrap_state_before_writing(client):
    c, tmp_path = client
    first = c.post(
        "/api/v1/setup/configure",
        json={
            "admin_token": "test-token-1234",
            "llm_provider": "deepseek",
            "llm_api_key": "sk-first-key",
        },
    )
    assert first.status_code == 200

    late_bootstrap = c.post(
        "/api/v1/setup/configure",
        json={
            "admin_token": "late-token-1234",
            "llm_provider": "deepseek",
            "llm_api_key": "sk-late-key",
        },
    )
    assert late_bootstrap.status_code == 401
    assert "APP_ADMIN_TOKEN=test-token-1234" in (tmp_path / ".env").read_text()

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/setup/configure",
            "headers": [],
            "state": {},
        }
    )
    request.state.admin_authenticated = True
    updated = asyncio.run(
        setup.configure_system(
            request,
            setup.ConfigureRequest(
                admin_token="updated-token-1234",
                llm_provider="deepseek",
                llm_api_key="sk-updated-key",
            ),
        )
    )
    assert updated["data"]["configured"] is True
    assert "APP_ADMIN_TOKEN=updated-token-1234" in (tmp_path / ".env").read_text()
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


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


@pytest.mark.parametrize("field", ["admin_token", "llm_api_key", "llm_base_url"])
def test_configure_rejects_env_line_injection(client, field):
    c, tmp_path = client
    payload = {
        "admin_token": "test-token-1234",
        "llm_provider": "deepseek",
        "llm_api_key": "sk-test-key",
        "llm_base_url": "https://api.deepseek.com",
    }
    payload[field] = "safe\nINJECTED=value"

    response = c.post("/api/v1/setup/configure", json=payload)

    assert response.status_code == 422
    assert not (tmp_path / ".env").exists()
