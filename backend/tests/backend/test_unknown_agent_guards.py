from __future__ import annotations


def test_unknown_agent_routes_do_not_provision_workspace(client, api_app):
    unknown_root = api_app["base_dir"] / "workspaces" / "ghost"

    responses = [
        client.post("/api/v1/agents/ghost/sessions", json={}),
        client.get("/api/v1/agents/ghost/files/index"),
        client.get("/api/v1/agents/ghost/tokens/session/s1"),
        client.get("/api/v1/agents/ghost/config/runtime"),
        client.get("/api/v1/hooks", params={"agent_id": "ghost"}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
    assert not unknown_root.exists()
