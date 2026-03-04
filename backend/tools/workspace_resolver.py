from __future__ import annotations

import re
from pathlib import Path


_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def resolve_project_root(runtime_root: Path, config_base_dir: Path | None = None) -> Path:
    if config_base_dir is not None:
        return config_base_dir
    if runtime_root.parent.name == "workspaces":
        return runtime_root.parent.parent
    return runtime_root


def is_valid_agent_id(value: str) -> bool:
    return bool(_AGENT_ID_PATTERN.fullmatch(value.strip()))


def infer_current_agent_id(runtime_root: Path) -> str:
    if runtime_root.parent.name == "workspaces" and is_valid_agent_id(runtime_root.name):
        return runtime_root.name
    return "default"


def list_agent_roots(project_root: Path) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    workspaces_dir = project_root / "workspaces"
    if workspaces_dir.exists():
        for path in sorted(workspaces_dir.iterdir(), key=lambda item: item.name):
            if path.is_dir() and is_valid_agent_id(path.name):
                rows.append((path.name, path))

    # Compatibility with tests/legacy layouts that place default workspace at project root.
    if not any(agent_id == "default" for agent_id, _ in rows):
        if (project_root / "workspace").exists():
            rows.append(("default", project_root))

    return rows


def resolve_agent_root(
    *,
    runtime_root: Path,
    config_base_dir: Path | None,
    requested_agent_id: str | None,
) -> tuple[str, Path]:
    project_root = resolve_project_root(runtime_root, config_base_dir)
    current_agent_id = infer_current_agent_id(runtime_root)
    agent_id = (requested_agent_id or current_agent_id).strip() or current_agent_id
    if not is_valid_agent_id(agent_id):
        raise ValueError("agent_id must match [A-Za-z0-9_-]{1,64}")

    workspaces_dir = project_root / "workspaces"
    candidate = workspaces_dir / agent_id
    if candidate.exists() and candidate.is_dir():
        return agent_id, candidate

    if agent_id == "default" and (project_root / "workspace").exists():
        return "default", project_root

    raise FileNotFoundError(f"Agent not found: {agent_id}")
