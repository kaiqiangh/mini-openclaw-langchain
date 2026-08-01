"""Setup API with bootstrap access and post-configuration admin auth."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.errors import ApiError
from config import load_config

router = APIRouter(tags=["setup"])

_BASE_DIR: Path | None = None
# ponytail: process-local bootstrap lock; multi-worker setup needs an OS-level lock.
_CONFIGURE_LOCK = threading.Lock()


def set_base_dir(base_dir: Path) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


class ConfigureRequest(BaseModel):
    admin_token: str = Field(min_length=8, max_length=128)
    llm_provider: str = Field(min_length=1, max_length=64)
    llm_api_key: str = Field(min_length=1, max_length=256)
    llm_base_url: str | None = Field(default=None, max_length=512)
    llm_model: str | None = Field(default=None, max_length=128)


def _require_single_line(name: str, value: str | None) -> None:
    if value is not None and ("\r" in value or "\n" in value):
        raise ApiError(
            status_code=422,
            code="validation_error",
            message=f"{name} must not contain line breaks",
        )


@router.get("/setup/status")
async def get_setup_status() -> dict[str, Any]:
    if _BASE_DIR is None:
        raise ApiError(status_code=500, code="not_initialized", message="Base dir not set")

    admin_token = (os.getenv("APP_ADMIN_TOKEN", "") or "").strip()

    llm_configured = False
    try:
        config = load_config(_BASE_DIR)
        for profile in config.llm_profiles.values():
            api_key = os.getenv(profile.api_key_env, "")
            if api_key and profile.base_url and profile.model:
                llm_configured = True
                break
    except Exception:
        pass

    default_agent_exists = (_BASE_DIR / "workspaces" / "default").exists()
    needs_setup = not admin_token or not llm_configured

    return {
        "data": {
            "needs_setup": needs_setup,
            "admin_token_configured": bool(admin_token),
            "llm_configured": llm_configured,
            "default_agent_exists": default_agent_exists,
        }
    }


@router.post("/setup/configure")
async def configure_system(request: Request, req: ConfigureRequest) -> dict[str, Any]:
    if _BASE_DIR is None:
        raise ApiError(status_code=500, code="not_initialized", message="Base dir not set")

    _require_single_line("admin_token", req.admin_token)
    _require_single_line("llm_api_key", req.llm_api_key)
    _require_single_line("llm_base_url", req.llm_base_url)

    provider = req.llm_provider.lower().strip()
    if provider not in {"deepseek", "openai"}:
        raise ApiError(
            status_code=422,
            code="validation_error",
            message=f"Unsupported provider: {provider}. Use 'deepseek' or 'openai'.",
        )

    with _CONFIGURE_LOCK:
        configured = (os.getenv("APP_ADMIN_TOKEN", "") or "").strip()
        if configured and not getattr(request.state, "admin_authenticated", False):
            raise ApiError(
                status_code=401,
                code="unauthorized",
                message="Missing or invalid admin token",
            )

        env_path = _BASE_DIR / ".env"
        env_lines: list[str] = []
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8").splitlines()
            for line in existing:
                if not line.startswith(("APP_ADMIN_TOKEN=", "DEEPSEEK_", "OPENAI_")):
                    env_lines.append(line)

        env_lines.append(f"APP_ADMIN_TOKEN={req.admin_token}")
        if provider == "deepseek":
            env_lines.append(f"DEEPSEEK_API_KEY={req.llm_api_key}")
            if req.llm_base_url:
                env_lines.append(f"DEEPSEEK_BASE_URL={req.llm_base_url}")
        else:
            env_lines.append(f"OPENAI_API_KEY={req.llm_api_key}")
            if req.llm_base_url:
                env_lines.append(f"OPENAI_BASE_URL={req.llm_base_url}")

        tmp_path = env_path.with_suffix(".tmp")
        tmp_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(env_path)

        os.environ["APP_ADMIN_TOKEN"] = req.admin_token
        if provider == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = req.llm_api_key
        else:
            os.environ["OPENAI_API_KEY"] = req.llm_api_key

    return {
        "data": {
            "configured": True,
            "admin_token_configured": True,
            "llm_provider": provider,
            "message": "Configuration saved. Restart the server to apply changes.",
        }
    }
