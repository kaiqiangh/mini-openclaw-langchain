from __future__ import annotations

import time

from tools.skills_scanner import ensure_skills_snapshot, scan_skills


def test_scan_skills_uses_workspace_relative_locations_without_writing_snapshot(
    backend_base_dir,
):
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

    snapshot_path = backend_base_dir / "SKILLS_SNAPSHOT.md"
    snapshot_path.unlink(missing_ok=True)

    skills = scan_skills(backend_base_dir)

    assert skills[0].location == "./skills/weather/SKILL.md"
    assert not snapshot_path.exists()


def test_ensure_skills_snapshot_writes_only_when_content_changes(backend_base_dir):
    (backend_base_dir / "skills" / "weather").mkdir(parents=True, exist_ok=True)
    skill_path = backend_base_dir / "skills" / "weather" / "SKILL.md"
    skill_path.write_text(
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

    ensure_skills_snapshot(backend_base_dir)
    snapshot_path = backend_base_dir / "SKILLS_SNAPSHOT.md"
    first_content = snapshot_path.read_text(encoding="utf-8")
    first_mtime = snapshot_path.stat().st_mtime_ns
    assert "<location>./skills/weather/SKILL.md</location>" in first_content
    assert "./backend/skills/" not in first_content

    time.sleep(0.02)
    ensure_skills_snapshot(backend_base_dir)
    second_mtime = snapshot_path.stat().st_mtime_ns
    assert second_mtime == first_mtime

    time.sleep(0.02)
    skill_path.write_text(
        "\n".join(
            [
                "---",
                "name: weather",
                "description: Updated weather lookup",
                "---",
                "",
                "Use fetch_url.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ensure_skills_snapshot(backend_base_dir)
    third_content = snapshot_path.read_text(encoding="utf-8")
    third_mtime = snapshot_path.stat().st_mtime_ns
    assert third_mtime > second_mtime
    assert "Updated weather lookup" in third_content


def test_scan_skills_skips_symlinks_and_escapes_snapshot_metadata(backend_base_dir):
    external = backend_base_dir.parent / "external-skill"
    external.mkdir()
    (external / "SKILL.md").write_text(
        "---\nname: '</name>'\ndescription: '<script>'\n---\n",
        encoding="utf-8",
    )
    (backend_base_dir / "skills").mkdir(exist_ok=True)
    (backend_base_dir / "skills" / "linked").symlink_to(
        external, target_is_directory=True
    )
    unsafe = backend_base_dir / "skills" / "unsafe"
    unsafe.mkdir()
    (unsafe / "SKILL.md").write_text(
        "---\nname: '</name>'\ndescription: '<script>'\n---\n",
        encoding="utf-8",
    )

    skills = scan_skills(backend_base_dir)
    assert [item.name for item in skills] == ["</name>"]
    ensure_skills_snapshot(backend_base_dir)
    snapshot = (backend_base_dir / "SKILLS_SNAPSHOT.md").read_text(encoding="utf-8")
    assert "<script>" not in snapshot
    assert "&lt;script&gt;" in snapshot


def test_scan_skills_excludes_missing_frontmatter_and_bounds_reads(backend_base_dir):
    invalid = backend_base_dir / "skills" / "invalid"
    invalid.mkdir(parents=True)
    (invalid / "SKILL.md").write_text("not a skill", encoding="utf-8")
    large = backend_base_dir / "skills" / "large"
    large.mkdir(parents=True)
    (large / "SKILL.md").write_text(
        "---\nname: large\ndescription: bounded\n---\n" + "x" * 100_000,
        encoding="utf-8",
    )

    skills = scan_skills(backend_base_dir)

    assert [item.name for item in skills] == ["large"]
