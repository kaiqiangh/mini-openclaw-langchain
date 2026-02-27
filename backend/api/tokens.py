from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.errors import ApiError
from graph.agent import AgentManager
from tools.path_guard import InvalidPathError, resolve_workspace_path

router = APIRouter(tags=["tokens"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None


class FileTokenRequest(BaseModel):
    paths: list[str]


def set_dependencies(base_dir: Path, agent_manager: AgentManager) -> None:
    global _BASE_DIR, _AGENT_MANAGER
    _BASE_DIR = base_dir
    _AGENT_MANAGER = agent_manager


def _token_count(text: str) -> int:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _require_deps() -> tuple[Path, AgentManager]:
    if _BASE_DIR is None or _AGENT_MANAGER is None:
        raise ApiError(status_code=500, code="not_initialized", message="Token dependencies are not initialized")
    return _BASE_DIR, _AGENT_MANAGER


@router.get("/tokens/session/{session_id}")
async def session_tokens(
    session_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    try:
        session_manager = agent_manager.get_session_manager(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    session = session_manager.load_session(session_id)
    if agent_manager.config is None:
        raise ApiError(status_code=500, code="not_initialized", message="Agent config unavailable")

    system_prompt = agent_manager.build_system_prompt(
        rag_mode=agent_manager.config.runtime.rag_mode,
        is_first_turn=len(session.get("messages", [])) == 0,
        agent_id=agent_id,
    )
    system_tokens = _token_count(system_prompt)

    message_tokens = 0
    for msg in session.get("messages", []):
        message_tokens += _token_count(str(msg.get("content", "")))

    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "system_tokens": system_tokens,
            "message_tokens": message_tokens,
            "total_tokens": system_tokens + message_tokens,
        }
    }


@router.post("/tokens/files")
async def file_tokens(
    request: FileTokenRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir, agent_manager = _require_deps()
    try:
        runtime = agent_manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    items: list[dict[str, Any]] = []
    for rel_path in request.paths:
        root_dir = base_dir if rel_path.startswith("skills/") else runtime.root_dir
        try:
            abs_path = resolve_workspace_path(root_dir, rel_path)
        except InvalidPathError:
            items.append({"path": rel_path, "tokens": 0, "error": "invalid_path"})
            continue

        if not abs_path.exists() or not abs_path.is_file():
            items.append({"path": rel_path, "tokens": 0, "error": "not_found"})
            continue

        content = abs_path.read_text(encoding="utf-8", errors="replace")
        items.append({"path": rel_path, "tokens": _token_count(content)})

    return {"data": items}
