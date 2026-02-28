from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.errors import ApiError
from graph.agent import AgentManager
from tools.path_guard import InvalidPathError, resolve_workspace_path
from tools.skills_scanner import scan_skills

router = APIRouter(tags=["files"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None

_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_BROWSE_DIRS = ("workspace", "memory", "knowledge")
_BROWSE_FILE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
_MAX_BROWSE_FILES = 1000


class SaveFileRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str


def set_dependencies(base_dir: Path, agent_manager: AgentManager) -> None:
    global _BASE_DIR, _AGENT_MANAGER
    _BASE_DIR = base_dir
    _AGENT_MANAGER = agent_manager


def _require_deps() -> tuple[Path, AgentManager]:
    if _BASE_DIR is None or _AGENT_MANAGER is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="File API dependencies are not initialized",
        )
    return _BASE_DIR, _AGENT_MANAGER


def _resolve_allowed_path(base_dir: Path, workspace_root: Path, rel_path: str) -> Path:
    rel_path = rel_path.strip()
    if rel_path in _ALLOWED_ROOT_FILES:
        target = workspace_root / rel_path
        return target.resolve()

    if not any(rel_path.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        raise ApiError(
            status_code=403,
            code="forbidden_path",
            message="Path prefix is not allowed",
            details={"path": rel_path},
        )

    path_root = base_dir if rel_path.startswith("skills/") else workspace_root
    try:
        return resolve_workspace_path(path_root, rel_path)
    except InvalidPathError as exc:
        raise ApiError(
            status_code=403,
            code="forbidden_path",
            message="Path escapes workspace root",
            details={"path": rel_path, "reason": str(exc)},
        ) from exc


def _list_workspace_files(workspace_root: Path) -> list[str]:
    rows: list[str] = []
    for rel_dir in _BROWSE_DIRS:
        root = workspace_root / rel_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _BROWSE_FILE_SUFFIXES:
                continue
            rows.append(path.relative_to(workspace_root).as_posix())
            if len(rows) >= _MAX_BROWSE_FILES:
                break
        if len(rows) >= _MAX_BROWSE_FILES:
            break
    for root_file in sorted(_ALLOWED_ROOT_FILES):
        if (workspace_root / root_file).is_file():
            rows.append(root_file)
    return sorted(set(rows))


@router.get("/files")
async def read_file(
    path: str = Query(..., min_length=1),
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir, agent_manager = _require_deps()
    try:
        runtime = agent_manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    target = _resolve_allowed_path(base_dir, runtime.root_dir, path)

    if not target.exists() or not target.is_file():
        raise ApiError(
            status_code=404,
            code="not_found",
            message="File not found",
            details={"path": path},
        )

    content = target.read_text(encoding="utf-8", errors="replace")
    return {"data": {"path": path, "content": content}}


@router.post("/files")
async def save_file(
    request: SaveFileRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir, agent_manager = _require_deps()
    try:
        runtime = agent_manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    target = _resolve_allowed_path(base_dir, runtime.root_dir, request.path)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(request.content, encoding="utf-8")
    tmp_path.replace(target)

    if request.path == "memory/MEMORY.md":
        runtime.memory_indexer.rebuild_index(
            settings=runtime.runtime_config.retrieval.memory
        )

    return {"data": {"path": request.path, "saved": True}}


@router.get("/skills")
async def list_skills() -> dict[str, Any]:
    base_dir, _ = _require_deps()
    skills = scan_skills(base_dir)
    items = [
        {
            "name": item.name,
            "description": item.description,
            "location": item.location,
        }
        for item in skills
    ]
    return {"data": items}


@router.get("/files/index")
async def list_workspace_files(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        runtime = agent_manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "agent_id": agent_id,
            "workspace_root": str(runtime.root_dir),
            "files": _list_workspace_files(runtime.root_dir),
        }
    }
