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
            "patch": {"llm_runtime": {"timeout_seconds": 15}},
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

    template_dir = api_app["base_dir"] / "agent_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "speedy.json").write_text(
        json.dumps(
            {
                "description": "Fast timeout profile",
                "runtime_config": {"llm_runtime": {"timeout_seconds": 12}},
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
