from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import FastAPI
from fastapi import Request
from fastapi.testclient import TestClient

from app import (
    AdminAuthMiddleware,
    RequestIdMiddleware,
    health as app_health,
    unhandled_error_handler,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AdminAuthMiddleware)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/secure")
    async def secure() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/setup/configure")
    async def configure() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_auth_exempts_health(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_does_not_load_runtime_config(monkeypatch):
    def fail_load_config(_):
        raise AssertionError("liveness must not load runtime config")

    monkeypatch.setattr("app.load_config", fail_load_config)
    assert asyncio.run(app_health()) == {"status": "ok"}


def test_auth_requires_configured_token(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/secure")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_not_configured"


def test_auth_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "secret-1")
    with TestClient(_build_app()) as client:
        missing = client.get("/api/v1/secure")
        wrong = client.get(
            "/api/v1/secure", headers={"Authorization": "Bearer wrong-value"}
        )
        wrong_raw = client.get(
            "/api/v1/secure", headers={"Authorization": "wrong-value"}
        )
        wrong_alt = client.get(
            "/api/v1/secure", headers={"X-Admin-Token": "wrong-value"}
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong_raw.status_code == 401
    assert wrong_alt.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_auth_accepts_valid_token(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "secret-1")
    with TestClient(_build_app()) as client:
        bearer_response = client.get(
            "/api/v1/secure", headers={"Authorization": "Bearer secret-1"}
        )
        raw_response = client.get(
            "/api/v1/secure", headers={"Authorization": "secret-1"}
        )
        alt_response = client.get(
            "/api/v1/secure", headers={"X-Admin-Token": "secret-1"}
        )
        cookie_response = client.get(
            "/api/v1/secure", cookies={"app_admin_token": "secret-1"}
        )
    assert bearer_response.status_code == 200
    assert raw_response.status_code == 200
    assert alt_response.status_code == 200
    assert cookie_response.status_code == 200


def test_setup_configure_is_public_only_before_admin_token_exists(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/setup/configure")
    assert response.status_code == 200


def test_setup_configure_requires_existing_admin_token_after_setup(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "secret-1")
    with TestClient(_build_app()) as client:
        missing = client.post("/api/v1/setup/configure")
        wrong = client.post(
            "/api/v1/setup/configure", headers={"Authorization": "Bearer wrong"}
        )
        valid = client.post(
            "/api/v1/setup/configure", headers={"Authorization": "Bearer secret-1"}
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert valid.status_code == 200


def test_unhandled_error_handler_hides_exception_details():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("leaked provider key from /tmp/private")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    payload = response.json()["error"]
    assert payload["code"] == "internal_error"
    assert payload["message"] == "Internal server error"
    assert "details" not in payload


def _build_request_id_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/")
    async def request_id(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    return app


def test_request_id_preserves_safe_bounded_value():
    request_id = "trace-abc_123:foo.bar"
    with TestClient(_build_request_id_app()) as client:
        response = client.get("/", headers={"X-Request-Id": request_id})

    assert response.json()["request_id"] == request_id
    assert response.headers["X-Request-Id"] == request_id


def test_request_id_replaces_invalid_or_overlong_value():
    for value in ("", "not safe", "a" * 129):
        with TestClient(_build_request_id_app()) as client:
            response = client.get("/", headers={"X-Request-Id": value})

        selected = response.json()["request_id"]
        assert selected == response.headers["X-Request-Id"]
        assert selected != value
        UUID(selected)
