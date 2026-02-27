from __future__ import annotations

from tools.skills_scanner import scan_skills


def test_skills_snapshot_uses_workspace_relative_locations(backend_base_dir):
    (backend_base_dir / "skills" / "weather").mkdir(parents=True, exist_ok=True)
    (backend_base_dir / "skills" / "weather" / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: weather",
                "description: Weather lookup",
                "---",
                "",
                "Use fetch_url.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    scan_skills(backend_base_dir)
    snapshot = (backend_base_dir / "SKILLS_SNAPSHOT.md").read_text(encoding="utf-8")
    assert "<location>./skills/weather/SKILL.md</location>" in snapshot
    assert "./backend/skills/" not in snapshot
