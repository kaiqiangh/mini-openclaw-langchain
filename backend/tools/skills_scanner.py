from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional at scaffold stage
    yaml = None

MAX_SKILL_READ_CHARS = 64 * 1024


@dataclass
class SkillMeta:
    name: str
    description: str
    location: str


def read_skill_text(path: Path) -> str:
    """Read only the bounded prefix used for cataloging and selection."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_SKILL_READ_CHARS)
    except OSError:
        return ""


def _extract_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            raw = "\n".join(lines[1:idx])
            if yaml is not None:
                try:
                    parsed = yaml.safe_load(raw) or {}
                except yaml.YAMLError:
                    return {}
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items()}
                return {}

            fallback: dict[str, str] = {}
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                fallback[k.strip()] = v.strip()
            return fallback
    return {}


def _iter_skill_files(skills_dir: Path) -> Iterable[Path]:
    if skills_dir.is_symlink() or not skills_dir.is_dir():
        return []
    root = skills_dir.resolve()
    files: list[Path] = []
    for candidate in sorted(skills_dir.glob("*/SKILL.md")):
        if candidate.is_symlink() or candidate.parent.is_symlink():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if candidate.is_file():
            files.append(candidate)
    return files


def scan_skills(base_dir: Path) -> list[SkillMeta]:
    skills_dir = base_dir / "skills"
    found: list[SkillMeta] = []

    for skill_file in _iter_skill_files(skills_dir):
        text = read_skill_text(skill_file)
        if not text:
            continue
        frontmatter = _extract_frontmatter(text)
        if not frontmatter.get("name", "").strip() or not frontmatter.get(
            "description", ""
        ).strip():
            continue

        name = frontmatter["name"].strip()
        description = frontmatter["description"].strip()

        # Skill paths in snapshot must be workspace-relative because tools are sandboxed to workspace root.
        rel_path = f"./skills/{skill_file.parent.name}/SKILL.md"
        found.append(SkillMeta(name=name, description=description, location=rel_path))

    return found


def render_skills_snapshot(skills: Iterable[SkillMeta]) -> str:
    lines = ["<available_skills>"]
    for item in skills:
        lines.extend(
            [
                "  <skill>",
                f"    <name>{escape(item.name)}</name>",
                f"    <description>{escape(item.description)}</description>",
                f"    <location>{escape(item.location)}</location>",
                "  </skill>",
            ]
        )
    lines.append("</available_skills>")
    return "\n".join(lines) + "\n"


def ensure_skills_snapshot(base_dir: Path) -> list[SkillMeta]:
    skills = scan_skills(base_dir)
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"
    content = render_skills_snapshot(skills)

    existing = ""
    if snapshot_path.exists() and snapshot_path.is_file():
        existing = snapshot_path.read_text(encoding="utf-8")

    if existing != content:
        snapshot_path.write_text(content, encoding="utf-8")

    return skills
