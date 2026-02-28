from __future__ import annotations

from pathlib import Path

from graph.agent import AgentManager


def test_workspace_seed_does_not_overwrite_existing_files(tmp_path: Path):
    base_dir = tmp_path
    workspaces_dir = base_dir / "workspaces"
    template_dir = base_dir / "workspace-template"
    agent_id = "elon"

    (template_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (template_dir / "memory").mkdir(parents=True, exist_ok=True)
    (template_dir / "knowledge").mkdir(parents=True, exist_ok=True)
    (base_dir / "skills" / "get_weather").mkdir(parents=True, exist_ok=True)
    (template_dir / "workspace" / "IDENTITY.md").write_text(
        "template-identity", encoding="utf-8"
    )
    (template_dir / "workspace" / "USER.md").write_text(
        "template-user", encoding="utf-8"
    )
    (base_dir / "skills" / "get_weather" / "SKILL.md").write_text(
        "upstream-skill", encoding="utf-8"
    )

    agent_root = workspaces_dir / agent_id
    (agent_root / "workspace").mkdir(parents=True, exist_ok=True)
    (agent_root / "workspace" / "IDENTITY.md").write_text(
        "custom-identity", encoding="utf-8"
    )
    (agent_root / "skills" / "get_weather").mkdir(parents=True, exist_ok=True)
    (agent_root / "skills" / "get_weather" / "SKILL.md").write_text(
        "custom-skill", encoding="utf-8"
    )

    manager = AgentManager()
    manager.base_dir = base_dir
    manager.workspaces_dir = workspaces_dir
    manager.workspace_template_dir = template_dir

    manager._ensure_workspace(agent_id)

    assert (agent_root / "workspace" / "IDENTITY.md").read_text(
        encoding="utf-8"
    ) == "custom-identity"
    # Missing file should still be seeded from template.
    assert (agent_root / "workspace" / "USER.md").read_text(
        encoding="utf-8"
    ) == "template-user"
    # Skill directory is synced from backend root but must not overwrite workspace custom edits.
    assert (agent_root / "skills" / "get_weather" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "custom-skill"


def test_workspace_seed_copies_default_config_once(tmp_path: Path):
    base_dir = tmp_path
    workspaces_dir = base_dir / "workspaces"
    template_dir = base_dir / "workspace-template"
    (template_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (template_dir / "memory").mkdir(parents=True, exist_ok=True)
    (template_dir / "knowledge").mkdir(parents=True, exist_ok=True)
    (base_dir / "config.json").write_text(
        '{"rag_mode": false, "agent_runtime": {"max_steps": 20}}\n', encoding="utf-8"
    )

    manager = AgentManager()
    manager.base_dir = base_dir
    manager.workspaces_dir = workspaces_dir
    manager.workspace_template_dir = template_dir

    alpha_root = manager._ensure_workspace("alpha")
    assert (alpha_root / "config.json").exists()
    assert '"max_steps": 20' in (alpha_root / "config.json").read_text(encoding="utf-8")

    # Existing agent config should not be overwritten by later backend default changes.
    (alpha_root / "config.json").write_text(
        '{"rag_mode": true, "agent_runtime": {"max_steps": 5}}\n', encoding="utf-8"
    )
    (base_dir / "config.json").write_text(
        '{"rag_mode": false, "agent_runtime": {"max_steps": 99}}\n', encoding="utf-8"
    )
    manager._ensure_workspace("alpha")
    assert '"max_steps": 5' in (alpha_root / "config.json").read_text(encoding="utf-8")
