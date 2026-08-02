"""Setup API with bootstrap access and post-configuration admin auth."""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from api.errors import ApiError
from config import load_config

router = APIRouter(tags=["setup"])

_BASE_DIR: Path | None = None
_RUNTIME_INITIALIZER: Callable[[], None] | None = None
# ponytail: process-local bootstrap lock; multi-worker setup needs an OS-level lock.
_CONFIGURE_LOCK = threading.Lock()


def set_base_dir(base_dir: Path) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


def set_runtime_initializer(initializer: Callable[[], None] | None) -> None:
    global _RUNTIME_INITIALIZER
    _RUNTIME_INITIALIZER = initializer


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


def _persist_provider_config(
    base_dir: Path,
    *,
    provider: str,
    base_url: str | None,
    model: str | None,
) -> None:
    config_path = base_dir / "config.json"
    payload: dict[str, Any] = {}
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
        except (OSError, json.JSONDecodeError):
            payload = {}

    profile_id = f"{provider}.setup"
    profiles = payload.setdefault("llm_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        payload["llm_profiles"] = profiles
    profiles[profile_id] = {
        "provider_id": provider,
        "driver": "openai_compatible",
        "base_url": base_url
        or (
            "https://api.deepseek.com"
            if provider == "deepseek"
            else "https://api.openai.com/v1"
        ),
        "model": model
        or ("deepseek-v4-flash" if provider == "deepseek" else "gpt-4o-mini"),
        "api_key_env": (
            "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
        ),
        "default_headers": {},
        "timeout_seconds": 60,
    }
    payload["default_llm_profile"] = profile_id
    llm_defaults = payload.setdefault("llm_defaults", {})
    if isinstance(llm_defaults, dict):
        llm_defaults["default"] = profile_id

    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    tmp_path.replace(config_path)


@router.get("/setup/status")
async def get_setup_status() -> dict[str, Any]:
    if _BASE_DIR is None:
        raise ApiError(
            status_code=500, code="not_initialized", message="Base dir not set"
        )

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
async def configure_system(
    request: Request,
    req: ConfigureRequest,
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    if _BASE_DIR is None:
        raise ApiError(
            status_code=500, code="not_initialized", message="Base dir not set"
        )

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

        _persist_provider_config(
            _BASE_DIR,
            provider=provider,
            base_url=req.llm_base_url,
            model=req.llm_model,
        )
        tmp_path = env_path.with_suffix(".tmp")
        tmp_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(env_path)

        os.environ["APP_ADMIN_TOKEN"] = req.admin_token
        if provider == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = req.llm_api_key
        else:
            os.environ["OPENAI_API_KEY"] = req.llm_api_key

        if _RUNTIME_INITIALIZER is not None:
            try:
                _RUNTIME_INITIALIZER()
            except Exception as exc:  # noqa: BLE001
                raise ApiError(
                    status_code=500,
                    code="runtime_initialization_failed",
                    message="Configuration was saved but the runtime could not start",
                ) from exc

    if response is not None:
        response.set_cookie(
            key="app_admin_token",
            value=req.admin_token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/api/v1",
            max_age=60 * 60 * 12,
        )

    return {
        "data": {
            "configured": True,
            "admin_token_configured": True,
            "llm_provider": provider,
            "message": "Configuration saved and runtime started.",
        }
    }
