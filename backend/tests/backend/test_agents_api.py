from __future__ import annotations

import json


def test_agents_bulk_export_patch_delete_and_runtime_diff(client, api_app):
    created_alpha = client.post("/api/v1/agents", json={"agent_id": "alpha"})
    created_beta = client.post("/api/v1/agents", json={"agent_id": "beta"})
    assert created_alpha.status_code == 201
    assert created_beta.status_code == 201

    exported = client.post(
        "/api/v1/agents/bulk-export",
        json={"agent_ids": ["alpha", "beta", "missing"], "format": "json"},
    )
    assert exported.status_code == 200
    exported_data = exported.json()["data"]
    assert exported_data["format"] == "json"
    assert len(exported_data["agents"]) == 2
    assert any(item["agent_id"] == "missing" for item in exported_data["errors"])

    patched = client.post(
        "/api/v1/agents/bulk-runtime-patch",
        json={
            "agent_ids": ["alpha", "beta"],
            "patch": {
                "llm_runtime": {"timeout_seconds": 15},
                "llm": {"default": "openai", "fallbacks": ["deepseek"]},
            },
            "mode": "merge",
        },
    )
    assert patched.status_code == 200
    patched_data = patched.json()["data"]
    assert patched_data["updated_count"] == 2
    assert all(item["updated"] is True for item in patched_data["results"])

    alpha_runtime = client.get("/api/v1/agents/alpha/config/runtime")
    assert alpha_runtime.status_code == 200
    assert alpha_runtime.json()["data"]["config"]["llm_runtime"]["timeout_seconds"] == 15
    assert alpha_runtime.json()["data"]["config"]["llm"]["default"] == "openai"
    assert alpha_runtime.json()["data"]["config"]["llm"]["fallbacks"] == ["deepseek"]

    template_dir = api_app["base_dir"] / "agent_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "speedy.json").write_text(
        json.dumps(
            {
                "description": "Fast timeout profile",
                "runtime_config": {
                    "llm_runtime": {"timeout_seconds": 12},
                    "llm": {"default": "azure_foundry", "fallbacks": []},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    listed_templates = client.get("/api/v1/agents/templates")
    assert listed_templates.status_code == 200
    template_names = [item["name"] for item in listed_templates.json()["data"]]
    assert "speedy" in template_names

    loaded_template = client.get("/api/v1/agents/templates/speedy")
    assert loaded_template.status_code == 200
    assert loaded_template.json()["data"]["runtime_config"]["llm_runtime"][
        "timeout_seconds"
    ] == 12
    assert loaded_template.json()["data"]["runtime_config"]["llm"]["default"] == (
        "azure_foundry"
    )

    diff = client.get(
        "/api/v1/agents/alpha/runtime-diff", params={"baseline": "template:speedy"}
    )
    assert diff.status_code == 200
    diff_data = diff.json()["data"]
    assert diff_data["baseline"] == "template:speedy"
    assert "summary" in diff_data

    deleted = client.post(
        "/api/v1/agents/bulk-delete", json={"agent_ids": ["alpha", "beta", "default"]}
    )
    assert deleted.status_code == 200
    deleted_data = deleted.json()["data"]
    assert deleted_data["deleted_count"] == 2
    assert any(
        item["agent_id"] == "default" and item["deleted"] is False
        for item in deleted_data["results"]
    )


def test_bulk_runtime_patch_rejects_invalid_mode(client):
    response = client.post(
        "/api/v1/agents/bulk-runtime-patch",
        json={"agent_ids": ["default"], "patch": {}, "mode": "invalid"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_agents_endpoint_includes_llm_status(client):
    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    rows = response.json()["data"]
    default_row = next(item for item in rows if item["agent_id"] == "default")
    assert default_row["llm_status"]["valid"] is True
    assert "default_profile" in default_row["llm_status"]


def test_bulk_runtime_patch_reports_legacy_llm_profile_validation_error(client):
    response = client.post(
        "/api/v1/agents/bulk-runtime-patch",
        json={
            "agent_ids": ["default"],
            "patch": {"llm_runtime": {"profile": "openai"}},
            "mode": "merge",
        },
    )
    assert response.status_code == 200
    result = response.json()["data"]["results"][0]
    assert result["updated"] is False
    assert "llm_runtime.profile" in result["error"]


def test_agent_tools_catalog_and_selection_update(client):
    listed = client.get("/api/v1/agents/default/tools")
    assert listed.status_code == 200
    payload = listed.json()["data"]
    assert payload["agent_id"] == "default"
    assert payload["triggers"] == ["chat", "heartbeat", "cron"]
    assert sorted(payload["enabled_tools"].keys()) == [
        "chat",
        "cron",
        "heartbeat",
    ]
    by_name = {item["name"]: item for item in payload["tools"]}
    assert "terminal" in by_name
    assert "read_files" in by_name
    assert by_name["terminal"]["trigger_status"]["chat"]["enabled"] is False

    updated = client.put(
        "/api/v1/agents/default/tools/selection",
        json={"trigger": "chat", "enabled_tools": ["terminal", "read_files"]},
    )
    assert updated.status_code == 200
    updated_payload = updated.json()["data"]
    assert "terminal" in updated_payload["enabled_tools"]["chat"]
    assert "read_files" in updated_payload["enabled_tools"]["chat"]
    updated_tools = {item["name"]: item for item in updated_payload["tools"]}
    assert updated_tools["terminal"]["trigger_status"]["chat"]["enabled"] is True
    assert (
        updated_tools["terminal"]["trigger_status"]["chat"]["explicitly_enabled"]
        is True
    )

    runtime = client.get("/api/v1/agents/default/config/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["data"]["config"]["chat_enabled_tools"] == [
        "terminal",
        "read_files",
    ]
    assert "chat_blocked_tools" in runtime.json()["data"]["config"]

    disable_read_files = client.put(
        "/api/v1/agents/default/tools/selection",
        json={"trigger": "chat", "enabled_tools": ["terminal"]},
    )
    assert disable_read_files.status_code == 200
    disabled_tools = {
        item["name"]: item["trigger_status"]["chat"]["enabled"]
        for item in disable_read_files.json()["data"]["tools"]
    }
    assert disabled_tools["read_files"] is False
    runtime_after_disable = client.get("/api/v1/agents/default/config/runtime")
    blocked = runtime_after_disable.json()["data"]["config"]["chat_blocked_tools"]
    assert "read_files" in blocked

    cron_reset = client.put(
        "/api/v1/agents/default/tools/selection",
        json={"trigger": "cron", "enabled_tools": []},
    )
    assert cron_reset.status_code == 200
    cron_enabled = cron_reset.json()["data"]["enabled_tools"]["cron"]
    assert cron_enabled == []
    cron_tools = {
        item["name"]: item["trigger_status"]["cron"]["enabled"]
        for item in cron_reset.json()["data"]["tools"]
    }
    assert cron_tools["read_files"] is False


def test_agent_tools_selection_rejects_unknown_tools(client):
    response = client.put(
        "/api/v1/agents/default/tools/selection",
        json={"trigger": "chat", "enabled_tools": ["terminal", "does_not_exist"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["unknown_tools"] == ["does_not_exist"]


def test_agent_tools_endpoints_return_not_found_for_unknown_agent(client):
    listed = client.get("/api/v1/agents/missing/tools")
    assert listed.status_code == 404
    assert listed.json()["error"]["code"] == "not_found"

    updated = client.put(
        "/api/v1/agents/missing/tools/selection",
        json={"trigger": "chat", "enabled_tools": []},
    )
    assert updated.status_code == 404
    assert updated.json()["error"]["code"] == "not_found"
