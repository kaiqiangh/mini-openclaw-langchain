"""Tests for global rate limiting."""
import os
import pytest
from starlette.requests import Request


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


def _request(client_host: str, headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/agents/default/chat",
            "raw_path": b"/api/v1/agents/default/chat",
            "scheme": "http",
            "query_string": b"",
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in (headers or {}).items()
            ],
            "client": (client_host, 1234),
            "server": ("testserver", 80),
            "root_path": "",
            "http_version": "1.1",
        }
    )


def test_rate_limit_ignores_forwarded_headers_by_default(monkeypatch):
    monkeypatch.delenv("APP_TRUST_PROXY_HEADERS", raising=False)
    request = _request("10.0.0.9", {"X-Real-IP": "203.0.113.7"})
    from app import RateLimitMiddleware

    assert RateLimitMiddleware._client_address(request) == "10.0.0.9"


def test_rate_limit_uses_valid_forwarded_client_when_proxy_is_trusted(monkeypatch):
    monkeypatch.setenv("APP_TRUST_PROXY_HEADERS", "true")
    request = _request(
        "10.0.0.9",
        {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.4"},
    )
    from app import RateLimitMiddleware

    assert RateLimitMiddleware._client_address(request) == "203.0.113.7"
    forwarded_request = _request(
        "10.0.0.9", {"X-Forwarded-For": "198.51.100.4, 203.0.113.7"}
    )
    assert RateLimitMiddleware._client_address(forwarded_request) == "203.0.113.7"
