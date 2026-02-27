from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sse_starlette.sse import AppStatus


async def _create_session(client: AsyncClient) -> str:
    response = await client.post("/api/sessions", json={})
    response.raise_for_status()
    return response.json()["data"]["session_id"]


async def _stream_chat(client: AsyncClient, session_id: str, message: str) -> str:
    async with client.stream(
        "POST",
        "/api/chat",
        json={"message": message, "session_id": session_id, "stream": True},
    ) as response:
        response.raise_for_status()
        return (await response.aread()).decode("utf-8", errors="replace")


@pytest.mark.asyncio
async def test_multi_session_stream_isolation(api_app):
    # Reset global SSE app status to current event loop to avoid cross-loop artifacts in tests.
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None

    app = api_app["app"]
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        session_ids = await asyncio.gather(*[_create_session(client) for _ in range(4)])
        payloads = await asyncio.gather(
            *[_stream_chat(client, session_id, f"msg-{i}") for i, session_id in enumerate(session_ids)]
        )

    for session_id, payload in zip(session_ids, payloads):
        assert f'"session_id": "{session_id}"' in payload

    for i, payload in enumerate(payloads):
        for j, session_id in enumerate(session_ids):
            if i == j:
                continue
            assert f'"session_id": "{session_id}"' not in payload
