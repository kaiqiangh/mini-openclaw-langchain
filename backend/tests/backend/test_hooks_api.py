from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from graph.tool_execution import ToolExecutionService


def _write_hook_handler(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_hooks_api_supports_crud_and_test(client, api_app):
    runtime = api_app["agent_manager"].get_runtime("default")
    _write_hook_handler(
        runtime.root_dir / "hooks" / "allow.py",
        (
            "from hooks.types import HookResult\n"
            "def handle(event):\n"
            "    return HookResult(allow=True, reason='ok')\n"
        ),
    )

    response = client.post(
        "/api/v1/hooks",
        params={"agent_id": "default"},
        json={
            "id": "allow-pre-run",
            "type": "pre_run",
            "handler": "hooks/allow.py",
            "mode": "sync",
            "timeout_ms": 5000,
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == "allow-pre-run"

    response = client.get("/api/v1/hooks", params={"agent_id": "default"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["handler"] == "hooks/allow.py"

    response = client.get("/api/v1/api/v1/hooks", params={"agent_id": "default"})
    assert response.status_code == 404

    response = client.post(
        "/api/v1/hooks/allow-pre-run/test",
        params={"agent_id": "default"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "hook_id": "allow-pre-run",
        "allow": True,
        "reason": "ok",
    }

    response = client.delete(
        "/api/v1/hooks/allow-pre-run",
        params={"agent_id": "default"},
    )
    assert response.status_code == 200
    assert response.json() == {"deleted": "allow-pre-run"}


async def _execute_tool_hook(agent_manager) -> None:
    runtime = agent_manager.get_runtime("default")
    hook_engine = agent_manager.get_hook_engine("default")

    mock_tool = AsyncMock()
    mock_tool.name = "terminal"
    mock_tool.ainvoke = AsyncMock(
        return_value='{"ok": true, "meta": {"duration_ms": 5}, "result": "done"}'
    )

    service = ToolExecutionService(
        tools=[mock_tool],
        tools_by_name={"terminal": mock_tool},
        hook_engine=hook_engine,
        audit_store=runtime.audit_store,
        trigger_type="chat",
        agent_id="default",
        run_id="run-hooks-audit",
        session_id="session-hooks-audit",
    )
    await service.execute_pending(
        [{"name": "terminal", "id": "call-1", "args": {"command": "pwd"}}]
    )


def test_hooks_audit_endpoint_returns_recent_hook_rows(client, api_app):
    runtime = api_app["agent_manager"].get_runtime("default")
    _write_hook_handler(
        runtime.root_dir / "hooks" / "tool_allow.py",
        (
            "from hooks.types import HookResult\n"
            "def handle(event):\n"
            "    return HookResult(allow=True)\n"
        ),
    )
    (runtime.root_dir / "hooks.json").write_text(
        (
            '{"hooks": ['
            '{"id": "pre-tool", "type": "pre_tool_use", "handler": "hooks/tool_allow.py", "mode": "sync"},'
            '{"id": "post-tool", "type": "post_tool_use", "handler": "hooks/tool_allow.py", "mode": "async"}'
            "]}\n"
        ),
        encoding="utf-8",
    )

    asyncio.run(_execute_tool_hook(api_app["agent_manager"]))

    response = client.get(
        "/api/v1/hooks/audit",
        params={"agent_id": "default", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert [row["event"] for row in data[:2]] == [
        "hook_post_tool_use",
        "hook_pre_tool_use",
    ]
    assert {row["details"]["hook_type"] for row in data[:2]} == {
        "post_tool_use",
        "pre_tool_use",
    }
    for row in data[:2]:
        assert row["session_id"] == "session-hooks-audit"
        assert row["run_id"] == "run-hooks-audit"
        assert row["details"]["agent_id"] == "default"
        assert row["details"]["session_id"] == "session-hooks-audit"
        assert row["details"]["run_id"] == "run-hooks-audit"
        assert row["details"]["timestamp"]
        assert row["details"]["tool_name"] == "terminal"
    post_tool_row = data[0]
    assert post_tool_row["details"]["result_preview"]
