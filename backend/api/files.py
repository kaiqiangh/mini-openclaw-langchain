from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.agent_guard import require_existing_runtime
from api.errors import ApiError
from graph.agent import AgentManager
from tools.path_guard import InvalidPathError, resolve_workspace_path
from tools.skills_scanner import ensure_skills_snapshot, scan_skills

router = APIRouter(tags=["files"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None

_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_BROWSE_DIRS = ("workspace", "memory", "knowledge")
_BROWSE_FILE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
_MAX_BROWSE_FILES = 1000
MAX_FILE_BYTES = 1_048_576
MAX_PATH_CHARS = 512


class SaveFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    content: str = Field(max_length=MAX_FILE_BYTES)


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


def _resolve_allowed_path(workspace_root: Path, rel_path: str) -> Path:
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

    try:
        return resolve_workspace_path(workspace_root, rel_path)
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
        if len(rows) >= _MAX_BROWSE_FILES:
            break
        if (workspace_root / root_file).is_file():
            rows.append(root_file)
    return sorted(set(rows))


def _serialize_skills(base_dir: Path) -> list[dict[str, str]]:
    return [
        {
            "name": item.name,
            "description": item.description,
            "location": item.location,
        }
        for item in scan_skills(base_dir)
    ]


@router.get("/agents/{agent_id}/files")
async def read_file(
    agent_id: str,
    path: str = Query(..., min_length=1, max_length=MAX_PATH_CHARS),
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        runtime = require_existing_runtime(agent_manager, agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    target = _resolve_allowed_path(runtime.root_dir, path)

    if not target.exists() or not target.is_file():
        raise ApiError(
            status_code=404,
            code="not_found",
            message="File not found",
            details={"path": path},
        )

    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ApiError(
            status_code=413,
            code="file_too_large",
            message=f"File exceeds the {MAX_FILE_BYTES} byte read limit",
            details={"path": path, "max_bytes": MAX_FILE_BYTES},
        )
    content = (await asyncio.to_thread(target.read_bytes))[:MAX_FILE_BYTES].decode(
        "utf-8", errors="replace"
    )
    return {"data": {"path": path, "content": content}}


@router.post("/agents/{agent_id}/files")
async def save_file(
    agent_id: str,
    request: SaveFileRequest,
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        runtime = require_existing_runtime(agent_manager, agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    target = _resolve_allowed_path(runtime.root_dir, request.path)

    content_bytes = request.content.encode("utf-8")
    if len(content_bytes) > MAX_FILE_BYTES:
        raise ApiError(
            status_code=413,
            code="file_too_large",
            message=f"File exceeds the {MAX_FILE_BYTES} byte write limit",
            details={"path": request.path, "max_bytes": MAX_FILE_BYTES},
        )

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        tmp_path.write_bytes(content_bytes)
        tmp_path.replace(target)

    await asyncio.to_thread(_write)

    if request.path == "memory/MEMORY.md":
        runtime.memory_indexer.schedule_rebuild(
            settings=runtime.runtime_config.retrieval.memory,
        )
    elif request.path.startswith("skills/"):
        await asyncio.to_thread(ensure_skills_snapshot, runtime.root_dir)

    return {"data": {"path": request.path, "saved": True}}


@router.get("/skills")
async def list_skills() -> dict[str, Any]:
    base_dir, _ = _require_deps()
    return {"data": _serialize_skills(base_dir)}


@router.get("/agents/{agent_id}/skills")
async def list_agent_skills(
    agent_id: str,
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        runtime = require_existing_runtime(agent_manager, agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc

    skills = ensure_skills_snapshot(runtime.root_dir)
    return {
        "data": [
            {
                "name": item.name,
                "description": item.description,
                "location": item.location,
            }
            for item in skills
        ]
    }


@router.get("/agents/{agent_id}/files/index")
async def list_workspace_files(
    agent_id: str,
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        runtime = require_existing_runtime(agent_manager, agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "agent_id": agent_id,
            "workspace_root": str(runtime.root_dir),
            "files": await asyncio.to_thread(_list_workspace_files, runtime.root_dir),
        }
    }
