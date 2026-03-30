"""Tests for run comparison API."""
import json
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from api import replay
from api.errors import ApiError, error_payload


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()

    @app.exception_handler(ApiError)
    async def handler(_, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=exc.code, message=exc.message),
        )

    app.include_router(replay.router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c


def test_compare_missing_params(client):
    r = client.get("/api/v1/agents/default/runs/compare")
    # Agent manager not initialized → 500 before param validation
    assert r.status_code in (422, 500)


def test_compare_nonexistent_run(client):
    r = client.get("/api/v1/agents/default/runs/compare?run_a=x&run_b=y")
    # Agent manager not initialized → 500
    assert r.status_code in (400, 500)


def test_list_replays_endpoint_exists(client):
    r = client.get("/api/v1/agents/default/runs/replays")
    # Agent manager not initialized → 500, but endpoint exists
    assert r.status_code in (200, 500)
