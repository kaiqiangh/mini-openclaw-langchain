from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import AdminAuthMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AdminAuthMiddleware)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/secure")
    async def secure() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_auth_exempts_health(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


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
        wrong_alt = client.get("/api/v1/secure", headers={"X-Admin-Token": "wrong-value"})
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
        raw_response = client.get("/api/v1/secure", headers={"Authorization": "secret-1"})
        alt_response = client.get("/api/v1/secure", headers={"X-Admin-Token": "secret-1"})
    assert bearer_response.status_code == 200
    assert raw_response.status_code == 200
    assert alt_response.status_code == 200
