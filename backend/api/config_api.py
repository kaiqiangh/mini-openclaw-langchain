from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from api.errors import ApiError
from config import load_config, save_runtime_config

router = APIRouter(tags=["config"])

_BASE_DIR: Path | None = None


class RagModeRequest(BaseModel):
    enabled: bool


def set_base_dir(base_dir: Path) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


def _require_base_dir() -> Path:
    if _BASE_DIR is None:
        raise ApiError(status_code=500, code="not_initialized", message="Config base directory is unavailable")
    return _BASE_DIR


@router.get("/config/rag-mode")
async def get_rag_mode() -> dict[str, Any]:
    base_dir = _require_base_dir()
    config = load_config(base_dir)
    return {"data": {"enabled": config.runtime.rag_mode}}


@router.put("/config/rag-mode")
async def set_rag_mode(request: RagModeRequest) -> dict[str, Any]:
    base_dir = _require_base_dir()
    config = load_config(base_dir)
    config.runtime.rag_mode = request.enabled
    save_runtime_config(base_dir, config.runtime)
    return {"data": {"enabled": request.enabled}}
