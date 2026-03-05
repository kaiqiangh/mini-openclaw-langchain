from __future__ import annotations


def _skill_doc(name: str, description: str) -> str:
    return (
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"Use {name}.",
            ]
        )
        + "\n"
    )


def test_agent_skills_listing_and_file_resolution_are_workspace_scoped(client):
    created = client.post("/api/v1/agents", json={"agent_id": "alpha"})
    assert created.status_code == 201

    default_save = client.post(
        "/api/v1/agents/default/files",
        json={
            "path": "skills/default_only/SKILL.md",
            "content": _skill_doc("default_only", "Default skill"),
        },
    )
    alpha_save = client.post(
        "/api/v1/agents/alpha/files",
        json={
            "path": "skills/alpha_only/SKILL.md",
            "content": _skill_doc("alpha_only", "Alpha skill"),
        },
    )
    assert default_save.status_code == 200
    assert alpha_save.status_code == 200
    default_snapshot = client.get(
        "/api/v1/agents/default/files", params={"path": "SKILLS_SNAPSHOT.md"}
    )
    alpha_snapshot = client.get(
        "/api/v1/agents/alpha/files", params={"path": "SKILLS_SNAPSHOT.md"}
    )
    assert default_snapshot.status_code == 200
    assert alpha_snapshot.status_code == 200
    assert "./skills/default_only/SKILL.md" in default_snapshot.json()["data"]["content"]
    assert "./skills/alpha_only/SKILL.md" in alpha_snapshot.json()["data"]["content"]

    default_skills = client.get("/api/v1/agents/default/skills")
    alpha_skills = client.get("/api/v1/agents/alpha/skills")
    assert default_skills.status_code == 200
    assert alpha_skills.status_code == 200

    default_locations = {
        item["location"]: item["description"] for item in default_skills.json()["data"]
    }
    alpha_locations = {
        item["location"]: item["description"] for item in alpha_skills.json()["data"]
    }
    assert "./skills/default_only/SKILL.md" in default_locations
    assert "./skills/default_only/SKILL.md" not in alpha_locations
    assert "./skills/alpha_only/SKILL.md" in alpha_locations
    assert "./skills/alpha_only/SKILL.md" not in default_locations

    default_read = client.get(
        "/api/v1/agents/default/files", params={"path": "skills/default_only/SKILL.md"}
    )
    alpha_read = client.get(
        "/api/v1/agents/alpha/files", params={"path": "skills/default_only/SKILL.md"}
    )
    assert default_read.status_code == 200
    assert "Default skill" in default_read.json()["data"]["content"]
    assert alpha_read.status_code == 404

    alpha_tokens = client.post(
        "/api/v1/agents/alpha/tokens/files",
        json={"paths": ["skills/alpha_only/SKILL.md", "skills/default_only/SKILL.md"]},
    )
    assert alpha_tokens.status_code == 200
    token_rows = {item["path"]: item for item in alpha_tokens.json()["data"]}
    assert token_rows["skills/alpha_only/SKILL.md"]["tokens"] > 0
    assert token_rows["skills/default_only/SKILL.md"]["error"] == "not_found"


def test_root_skill_listing_does_not_create_snapshot(client, api_app):
    base_dir = api_app["base_dir"]
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"
    snapshot_path.unlink(missing_ok=True)
    (base_dir / "skills" / "root_only").mkdir(parents=True, exist_ok=True)
    (base_dir / "skills" / "root_only" / "SKILL.md").write_text(
        _skill_doc("root_only", "Root skill"),
        encoding="utf-8",
    )

    listed = client.get("/api/v1/skills")
    assert listed.status_code == 200
    assert any(
        item["location"] == "./skills/root_only/SKILL.md"
        for item in listed.json()["data"]
    )
    assert not snapshot_path.exists()
