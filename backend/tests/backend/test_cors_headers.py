"""Tests for CORS header policy."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "test-cors-token")
    yield
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)


@pytest.fixture()
def client():
    from importlib import reload
    import app as app_module
    reload(app_module)
    from app import app
    return TestClient(app)


def test_cors_preflight_echoes_only_configured_headers(client: TestClient):
    """CORS preflight must not echo arbitrary requested headers."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Evil-Header",
        },
    )
    allowed = response.headers.get("access-control-allow-headers", "")
    assert "X-Evil-Header" not in allowed, (
        f"Wildcard header allowance permits arbitrary headers: {allowed}"
    )


def test_cors_allows_authorization_header(client: TestClient):
    """Authorization header must be in the allowed list."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed, (
        f"Authorization header must be allowed: {allowed}"
    )
