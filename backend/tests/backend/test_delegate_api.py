from __future__ import annotations

import asyncio
import threading
import time

from api import delegates as delegates_api
from tools.delegate_registry import DelegateRegistry


def test_delegate_list_and_detail_endpoints(client, api_app):
    registry = api_app["delegate_registry"]
    parent_session = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = parent_session["data"]["session_id"]
    reg = registry.register(
        "default",
        session_id,
        "Research APIs",
        "researcher",
        ["web_search"],
        [],
        30,
    )
    registry.mark_completed(
        reg["delegate_id"],
        {
            "summary": "Found docs",
            "steps": 2,
            "tools_used": ["web_search"],
            "token_usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    )

    listed = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/delegates"
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["delegates"][0]["delegate_id"] == reg["delegate_id"]

    detail = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/delegates/{reg['delegate_id']}"
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["delegate_id"] == reg["delegate_id"]
    assert detail_payload["result_summary"] == "Found docs"


def test_delegate_api_survives_registry_rehydration(client, api_app):
    registry = api_app["delegate_registry"]
    parent_session = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = parent_session["data"]["session_id"]
    reg = registry.register(
        "default",
        session_id,
        "Investigate issue",
        "researcher",
        ["web_search"],
        [],
        30,
    )
    registry.mark_failed(reg["delegate_id"], "boom")

    api_app["delegate_registry"] = DelegateRegistry(api_app["base_dir"])
    delegates_api.set_delegate_registry(api_app["delegate_registry"])

    detail = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/delegates/{reg['delegate_id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"


def test_delegate_stream_endpoint_emits_terminal_state(client, api_app):
    registry = api_app["delegate_registry"]
    parent_session = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = parent_session["data"]["session_id"]
    reg = registry.register(
        "default",
        session_id,
        "Research APIs",
        "researcher",
        ["web_search"],
        [],
        30,
    )

    def _complete() -> None:
        time.sleep(0.05)
        registry.mark_completed(
            reg["delegate_id"],
            {
                "summary": "done",
                "steps": 1,
                "tools_used": ["web_search"],
                "token_usage": {},
            },
        )

    task = threading.Thread(target=_complete)
    task.start()
    with client.stream(
        "GET",
        f"/api/v1/agents/default/sessions/{session_id}/delegates/{reg['delegate_id']}/stream",
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    task.join()

    assert '"status": "completed"' in body
