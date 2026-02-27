from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None


class InjectionMode(str, Enum):
    EVERY_TURN = "every_turn"
    FIRST_TURN_ONLY = "first_turn_only"


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    GOOGLE_AI_STUDIO = "google_ai_studio"


@dataclass
class ToolTimeouts:
    terminal_seconds: int = 30
    python_repl_seconds: int = 30
    fetch_url_seconds: int = 15


@dataclass
class ToolOutputLimits:
    terminal_chars: int = 5000
    fetch_url_chars: int = 5000
    read_file_chars: int = 10000


@dataclass
class AutonomousToolsConfig:
    heartbeat_enabled_tools: list[str] = field(default_factory=list)
    cron_enabled_tools: list[str] = field(default_factory=list)


@dataclass
class HeartbeatRuntimeConfig:
    enabled: bool = False
    interval_seconds: int = 300
    timezone: str = "UTC"
    active_start_hour: int = 9
    active_end_hour: int = 21
    session_id: str = "__heartbeat__"


@dataclass
class CronRuntimeConfig:
    enabled: bool = True
    poll_interval_seconds: int = 20
    timezone: str = "UTC"
    max_failures: int = 8
    retry_base_seconds: int = 30
    retry_max_seconds: int = 3600
    failure_retention: int = 200


@dataclass
class RuntimeConfig:
    rag_mode: bool = False
    injection_mode: InjectionMode = InjectionMode.EVERY_TURN
    bootstrap_max_chars: int = 20000
    bootstrap_total_max_chars: int = 150000
    tool_timeouts: ToolTimeouts = field(default_factory=ToolTimeouts)
    tool_output_limits: ToolOutputLimits = field(default_factory=ToolOutputLimits)
    autonomous_tools: AutonomousToolsConfig = field(default_factory=AutonomousToolsConfig)
    heartbeat: HeartbeatRuntimeConfig = field(default_factory=HeartbeatRuntimeConfig)
    cron: CronRuntimeConfig = field(default_factory=CronRuntimeConfig)


@dataclass
class SecretConfig:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    embedding_provider: EmbeddingProvider
    openai_api_key: str
    openai_base_url: str
    embedding_model: str
    google_api_key: str
    google_embedding_model: str


@dataclass
class AppConfig:
    base_dir: Path
    runtime: RuntimeConfig
    secrets: SecretConfig


def _load_runtime_config(config_path: Path) -> RuntimeConfig:
    if not config_path.exists():
        return RuntimeConfig()

    payload: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))

    tool_timeouts = payload.get("tool_timeouts", {})
    tool_output_limits = payload.get("tool_output_limits", {})
    autonomous_tools = payload.get("autonomous_tools", {})
    heartbeat = payload.get("heartbeat", {})
    cron = payload.get("cron", {})

    injection_value = payload.get("injection_mode", InjectionMode.EVERY_TURN.value)
    try:
        injection_mode = InjectionMode(injection_value)
    except ValueError:
        injection_mode = InjectionMode.EVERY_TURN

    return RuntimeConfig(
        rag_mode=bool(payload.get("rag_mode", False)),
        injection_mode=injection_mode,
        bootstrap_max_chars=int(payload.get("bootstrap_max_chars", 20000)),
        bootstrap_total_max_chars=int(payload.get("bootstrap_total_max_chars", 150000)),
        tool_timeouts=ToolTimeouts(
            terminal_seconds=int(tool_timeouts.get("terminal_seconds", 30)),
            python_repl_seconds=int(tool_timeouts.get("python_repl_seconds", 30)),
            fetch_url_seconds=int(tool_timeouts.get("fetch_url_seconds", 15)),
        ),
        tool_output_limits=ToolOutputLimits(
            terminal_chars=int(tool_output_limits.get("terminal_chars", 5000)),
            fetch_url_chars=int(tool_output_limits.get("fetch_url_chars", 5000)),
            read_file_chars=int(tool_output_limits.get("read_file_chars", 10000)),
        ),
        autonomous_tools=AutonomousToolsConfig(
            heartbeat_enabled_tools=list(autonomous_tools.get("heartbeat_enabled_tools", [])),
            cron_enabled_tools=list(autonomous_tools.get("cron_enabled_tools", [])),
        ),
        heartbeat=HeartbeatRuntimeConfig(
            enabled=bool(heartbeat.get("enabled", False)),
            interval_seconds=max(30, int(heartbeat.get("interval_seconds", 300))),
            timezone=str(heartbeat.get("timezone", "UTC")),
            active_start_hour=int(heartbeat.get("active_start_hour", 9)) % 24,
            active_end_hour=int(heartbeat.get("active_end_hour", 21)) % 24,
            session_id=str(heartbeat.get("session_id", "__heartbeat__")),
        ),
        cron=CronRuntimeConfig(
            enabled=bool(cron.get("enabled", True)),
            poll_interval_seconds=max(5, int(cron.get("poll_interval_seconds", 20))),
            timezone=str(cron.get("timezone", "UTC")),
            max_failures=max(1, int(cron.get("max_failures", 8))),
            retry_base_seconds=max(5, int(cron.get("retry_base_seconds", 30))),
            retry_max_seconds=max(30, int(cron.get("retry_max_seconds", 3600))),
            failure_retention=max(1, int(cron.get("failure_retention", 200))),
        ),
    )


def _load_secrets() -> SecretConfig:
    provider_raw = os.getenv("EMBEDDING_PROVIDER", EmbeddingProvider.OPENAI.value)
    try:
        embedding_provider = EmbeddingProvider(provider_raw)
    except ValueError:
        embedding_provider = EmbeddingProvider.OPENAI

    return SecretConfig(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        embedding_provider=embedding_provider,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_embedding_model=os.getenv("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
    )


def validate_required_secrets(secrets: SecretConfig) -> list[str]:
    missing: list[str] = []
    if not secrets.deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if secrets.embedding_provider == EmbeddingProvider.OPENAI:
        if not secrets.openai_api_key:
            missing.append("OPENAI_API_KEY")
    elif secrets.embedding_provider == EmbeddingProvider.GOOGLE_AI_STUDIO:
        if not secrets.google_api_key:
            missing.append("GOOGLE_API_KEY")
    return missing


def load_config(base_dir: Path) -> AppConfig:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=base_dir / ".env", override=False)
    runtime = _load_runtime_config(base_dir / "config.json")
    secrets = _load_secrets()
    return AppConfig(base_dir=base_dir, runtime=runtime, secrets=secrets)


def save_runtime_config(base_dir: Path, runtime: RuntimeConfig) -> None:
    payload = {
        "rag_mode": runtime.rag_mode,
        "injection_mode": runtime.injection_mode.value,
        "bootstrap_max_chars": runtime.bootstrap_max_chars,
        "bootstrap_total_max_chars": runtime.bootstrap_total_max_chars,
        "tool_timeouts": {
            "terminal_seconds": runtime.tool_timeouts.terminal_seconds,
            "python_repl_seconds": runtime.tool_timeouts.python_repl_seconds,
            "fetch_url_seconds": runtime.tool_timeouts.fetch_url_seconds,
        },
        "tool_output_limits": {
            "terminal_chars": runtime.tool_output_limits.terminal_chars,
            "fetch_url_chars": runtime.tool_output_limits.fetch_url_chars,
            "read_file_chars": runtime.tool_output_limits.read_file_chars,
        },
        "autonomous_tools": {
            "heartbeat_enabled_tools": list(runtime.autonomous_tools.heartbeat_enabled_tools),
            "cron_enabled_tools": list(runtime.autonomous_tools.cron_enabled_tools),
        },
        "heartbeat": {
            "enabled": runtime.heartbeat.enabled,
            "interval_seconds": runtime.heartbeat.interval_seconds,
            "timezone": runtime.heartbeat.timezone,
            "active_start_hour": runtime.heartbeat.active_start_hour,
            "active_end_hour": runtime.heartbeat.active_end_hour,
            "session_id": runtime.heartbeat.session_id,
        },
        "cron": {
            "enabled": runtime.cron.enabled,
            "poll_interval_seconds": runtime.cron.poll_interval_seconds,
            "timezone": runtime.cron.timezone,
            "max_failures": runtime.cron.max_failures,
            "retry_base_seconds": runtime.cron.retry_base_seconds,
            "retry_max_seconds": runtime.cron.retry_max_seconds,
            "failure_retention": runtime.cron.failure_retention,
        },
    }
    (base_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
