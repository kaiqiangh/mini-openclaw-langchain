from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from api.agent_guard import require_existing_runtime
from api.errors import ApiError
from graph.agent import AgentManager
from graph.session_manager import InvalidSessionIdError, LegacySessionStateError
from tools.path_guard import InvalidPathError, resolve_workspace_path

router = APIRouter(tags=["tokens"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None
MAX_TOKEN_FILES = 32
MAX_TOKEN_FILE_BYTES = 256_000
MAX_TOKEN_TOTAL_BYTES = 1_048_576
MAX_PATH_CHARS = 512
MAX_SESSION_TOKEN_MESSAGES = 1000
MAX_SESSION_TOKEN_BYTES = 1_048_576
MAX_SESSION_TOKEN_COUNT = 100_000


class FileTokenRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=MAX_TOKEN_FILES)

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        if any(not path.strip() or len(path) > MAX_PATH_CHARS for path in value):
            raise ValueError(f"paths must be non-empty and at most {MAX_PATH_CHARS} characters")
        return value


def set_dependencies(base_dir: Path, agent_manager: AgentManager) -> None:
    global _BASE_DIR, _AGENT_MANAGER
    _BASE_DIR = base_dir
    _AGENT_MANAGER = agent_manager


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    try:
        return len(_encoding().encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _require_deps() -> tuple[Path, AgentManager]:
    if _BASE_DIR is None or _AGENT_MANAGER is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Token dependencies are not initialized",
        )
    return _BASE_DIR, _AGENT_MANAGER


def _legacy_state_api_error(exc: LegacySessionStateError) -> ApiError:
    return ApiError(
        status_code=409,
        code="unsupported_legacy_state",
        message=str(exc),
    )


def _session_token_budget_error(
    *, reason: str, message_count: int, total_bytes: int, total_tokens: int
) -> ApiError:
    return ApiError(
        status_code=413,
        code="session_token_budget_exceeded",
        message="Session token count exceeds the bounded request budget",
        details={
            "reason": reason,
            "message_count": message_count,
            "total_bytes": total_bytes,
            "total_tokens": total_tokens,
            "max_messages": MAX_SESSION_TOKEN_MESSAGES,
            "max_bytes": MAX_SESSION_TOKEN_BYTES,
            "max_tokens": MAX_SESSION_TOKEN_COUNT,
        },
    )


@router.get("/agents/{agent_id}/tokens/session/{session_id}")
async def session_tokens(
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    runtime = require_existing_runtime(agent_manager, agent_id)
    repository = agent_manager.get_session_repository(agent_id)
    try:
        snapshot = await repository.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            include_live=False,
            create_if_missing=True,
        )
    except InvalidSessionIdError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    except LegacySessionStateError as exc:
        raise _legacy_state_api_error(exc) from exc
    messages = snapshot.messages
    if agent_manager.config is None:
        raise ApiError(
            status_code=500, code="not_initialized", message="Agent config unavailable"
        )
    system_prompt = agent_manager.build_system_prompt(
        rag_mode=runtime.runtime_config.rag_mode,
        is_first_turn=len(messages) == 0,
        agent_id=agent_id,
    )
    total_bytes = len(system_prompt.encode("utf-8"))
    if len(messages) > MAX_SESSION_TOKEN_MESSAGES:
        raise _session_token_budget_error(
            reason="message_count",
            message_count=len(messages),
            total_bytes=total_bytes,
            total_tokens=0,
        )
    if total_bytes > MAX_SESSION_TOKEN_BYTES:
        raise _session_token_budget_error(
            reason="system_prompt",
            message_count=0,
            total_bytes=total_bytes,
            total_tokens=0,
        )
    system_tokens = _token_count(system_prompt)
    if system_tokens > MAX_SESSION_TOKEN_COUNT:
        raise _session_token_budget_error(
            reason="system_prompt",
            message_count=0,
            total_bytes=total_bytes,
            total_tokens=system_tokens,
        )

    message_tokens = 0
    for message_index, msg in enumerate(messages, start=1):
        content = str(msg.get("content", ""))
        total_bytes += len(content.encode("utf-8"))
        if total_bytes > MAX_SESSION_TOKEN_BYTES:
            raise _session_token_budget_error(
                reason="byte_count",
                message_count=message_index,
                total_bytes=total_bytes,
                total_tokens=system_tokens + message_tokens,
            )
        message_tokens += _token_count(content)
        if system_tokens + message_tokens > MAX_SESSION_TOKEN_COUNT:
            raise _session_token_budget_error(
                reason="token_count",
                message_count=message_index,
                total_bytes=total_bytes,
                total_tokens=system_tokens + message_tokens,
            )

    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "system_tokens": system_tokens,
            "message_tokens": message_tokens,
            "total_tokens": system_tokens + message_tokens,
        }
    }


@router.post("/agents/{agent_id}/tokens/files")
async def file_tokens(
    agent_id: str,
    request: FileTokenRequest,
) -> dict[str, Any]:
    _, agent_manager = _require_deps()
    runtime = require_existing_runtime(agent_manager, agent_id)

    items: list[dict[str, Any]] = []
    total_bytes = 0
    for rel_path in request.paths:
        try:
            abs_path = resolve_workspace_path(runtime.root_dir, rel_path)
        except InvalidPathError:
            items.append({"path": rel_path, "tokens": 0, "error": "invalid_path"})
            continue

        if not abs_path.exists() or not abs_path.is_file():
            items.append({"path": rel_path, "tokens": 0, "error": "not_found"})
            continue

        size = abs_path.stat().st_size
        if size > MAX_TOKEN_FILE_BYTES:
            items.append({"path": rel_path, "tokens": 0, "error": "file_too_large"})
            continue
        if total_bytes + size > MAX_TOKEN_TOTAL_BYTES:
            items.append({"path": rel_path, "tokens": 0, "error": "total_size_limit"})
            continue
        total_bytes += size
        content = await asyncio.to_thread(
            lambda: abs_path.read_bytes().decode("utf-8", errors="replace")
        )
        items.append({"path": rel_path, "tokens": _token_count(content)})

    return {"data": items}
