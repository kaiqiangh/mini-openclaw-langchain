from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sse_starlette.sse import AppStatus


@pytest.mark.asyncio
async def test_stream_continues_after_client_disconnect(api_app):
    AppStatus.should_exit = False
    if hasattr(AppStatus, "should_exit_event"):
        setattr(AppStatus, "should_exit_event", None)

    manager = api_app["agent_manager"]
    repository = manager.get_session_repository("default")

    async def delayed_stream(self, message: str, session_id: str, **kwargs):
        _ = kwargs
        await repository.append_message(
            agent_id="default",
            session_id=session_id,
            role="user",
            content=message,
        )
        yield {"type": "run_start", "data": {"run_id": "run-bg", "attempt": 1}}
        await asyncio.sleep(0.25)
        yield {"type": "token", "data": {"content": f"[{session_id}]"}}
        await asyncio.sleep(0.25)
        yield {"type": "token", "data": {"content": message}}
        await asyncio.sleep(0.25)
        await repository.append_message(
            agent_id="default",
            session_id=session_id,
            role="assistant",
            content=f"[{session_id}]{message}",
        )
        yield {
            "type": "done",
            "data": {
                "content": f"[{session_id}]{message}",
                "session_id": session_id,
                "run_id": "run-bg",
            },
        }

    manager.astream = delayed_stream.__get__(manager, type(manager))

    transport = ASGITransport(app=api_app["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/v1/agents/default/sessions", json={})
        created.raise_for_status()
        session_id = created.json()["data"]["session_id"]

        async with client.stream(
            "POST",
            "/api/v1/agents/default/chat",
            json={"message": "hello", "session_id": session_id, "stream": True},
        ) as response:
            response.raise_for_status()
            # Disconnect immediately; backend run should continue independently.
            await asyncio.sleep(0.05)

        # Disconnecting the stream should not stop the backend run.
        await asyncio.sleep(1.0)
        final_history = (
            await client.get(f"/api/v1/agents/default/sessions/{session_id}/history")
        ).json()["data"]["messages"]

    assert any(
        row.get("role") == "assistant" and row.get("content", "").endswith("hello")
        for row in final_history
    )
    assert not any(bool(row.get("streaming", False)) for row in final_history)
