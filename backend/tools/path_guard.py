from __future__ import annotations

from pathlib import Path


class InvalidPathError(ValueError):
    pass


def resolve_workspace_path(root_dir: Path, candidate_path: str) -> Path:
    raw = candidate_path.strip()
    if raw == "":
        raise InvalidPathError("Path must not be empty")

    candidate_input = Path(raw)
    if candidate_input.is_absolute():
        raise InvalidPathError("Absolute paths are not allowed")

    if any(part == ".." for part in candidate_input.parts):
        raise InvalidPathError("Parent directory traversal '..' is not allowed")

    root = root_dir.resolve()
    candidate = (root / candidate_input).resolve()

    if not candidate.is_relative_to(root):
        raise InvalidPathError(f"Path escapes workspace root: {candidate_path}")

    return candidate
