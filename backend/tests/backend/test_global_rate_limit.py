"""Tests for global rate limiting."""
import os
import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "test-rl-token")
    monkeypatch.setenv("APP_TRUSTED_HOSTS", "testserver,localhost,127.0.0.1")
    yield
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("APP_TRUSTED_HOSTS", raising=False)


@pytest.fixture()
def client():
    from importlib import reload
    import app as app_module
    reload(app_module)
    from app import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_global_rate_limit_configured(client):
    """RateLimitMiddleware must have a global limit configured."""
    from app import app, RateLimitMiddleware
    found = any(mw.cls is RateLimitMiddleware for mw in app.user_middleware)
    assert found, "RateLimitMiddleware must be registered"


def test_health_endpoint_exempt_from_rate_limit(client):
    """Health endpoint must not count against rate limits."""
    headers = {"Authorization": "Bearer test-rl-token"}
    for _ in range(5):
        response = client.get("/api/v1/health", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
