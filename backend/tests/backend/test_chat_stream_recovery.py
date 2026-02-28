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

    async def delayed_stream(
        self, message: str, history: list[dict[str, object]], session_id: str, **kwargs
    ):
        _ = history, kwargs
        yield {"type": "run_start", "data": {"run_id": "run-bg", "attempt": 1}}
        yield {"type": "token", "data": {"content": f"[{session_id}]"}}
        await asyncio.sleep(0.2)
        yield {"type": "token", "data": {"content": message}}
        await asyncio.sleep(0.2)
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
        created = await client.post("/api/sessions", json={})
        created.raise_for_status()
        session_id = created.json()["data"]["session_id"]

        async with client.stream(
            "POST",
            "/api/chat",
            json={"message": "hello", "session_id": session_id, "stream": True},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("event: token"):
                    break

            # While still running, live response should be visible in history.
            live_history = (
                await client.get(f"/api/sessions/{session_id}/history")
            ).json()["data"]["messages"]
            assert live_history
            assert bool(live_history[-1].get("streaming", False)) is True

        # Disconnecting the stream should not stop the backend run.
        await asyncio.sleep(0.5)
        final_history = (
            await client.get(f"/api/sessions/{session_id}/history")
        ).json()["data"]["messages"]

    assert any(
        row.get("role") == "assistant" and row.get("content", "").endswith("hello")
        for row in final_history
    )
    assert not any(bool(row.get("streaming", False)) for row in final_history)
