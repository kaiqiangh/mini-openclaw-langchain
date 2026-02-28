from __future__ import annotations

import json
import os
import hashlib
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
class AgentExecutionConfig:
    max_steps: int = 20
    max_retries: int = 1


@dataclass
class LlmRuntimeConfig:
    temperature: float = 0.2
    timeout_seconds: int = 60


@dataclass
class RetrievalDomainConfig:
    top_k: int = 3
    semantic_weight: float = 0.7
    lexical_weight: float = 0.3
    chunk_size: int = 256
    chunk_overlap: int = 32


@dataclass
class RetrievalConfig:
    memory: RetrievalDomainConfig = field(default_factory=RetrievalDomainConfig)
    knowledge: RetrievalDomainConfig = field(
        default_factory=lambda: RetrievalDomainConfig(
            top_k=3,
            semantic_weight=0.7,
            lexical_weight=0.3,
            chunk_size=400,
            chunk_overlap=80,
        )
    )


@dataclass
class ToolRetryGuardConfig:
    repeat_identical_failure_limit: int = 2


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
    agent_runtime: AgentExecutionConfig = field(default_factory=AgentExecutionConfig)
    llm_runtime: LlmRuntimeConfig = field(default_factory=LlmRuntimeConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    tool_retry_guard: ToolRetryGuardConfig = field(default_factory=ToolRetryGuardConfig)
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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _deep_diff(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key, value in candidate.items():
        baseline_value = baseline.get(key)
        if isinstance(value, dict) and isinstance(baseline_value, dict):
            nested = _deep_diff(value, baseline_value)
            if nested:
                diff[key] = nested
            continue
        if value != baseline_value:
            diff[key] = value
    return diff


def _runtime_to_payload(runtime: RuntimeConfig) -> dict[str, Any]:
    return {
        "rag_mode": runtime.rag_mode,
        "injection_mode": runtime.injection_mode.value,
        "bootstrap_max_chars": runtime.bootstrap_max_chars,
        "bootstrap_total_max_chars": runtime.bootstrap_total_max_chars,
        "agent_runtime": {
            "max_steps": runtime.agent_runtime.max_steps,
            "max_retries": runtime.agent_runtime.max_retries,
        },
        "llm_runtime": {
            "temperature": runtime.llm_runtime.temperature,
            "timeout_seconds": runtime.llm_runtime.timeout_seconds,
        },
        "retrieval": {
            "memory": {
                "top_k": runtime.retrieval.memory.top_k,
                "semantic_weight": runtime.retrieval.memory.semantic_weight,
                "lexical_weight": runtime.retrieval.memory.lexical_weight,
                "chunk_size": runtime.retrieval.memory.chunk_size,
                "chunk_overlap": runtime.retrieval.memory.chunk_overlap,
            },
            "knowledge": {
                "top_k": runtime.retrieval.knowledge.top_k,
                "semantic_weight": runtime.retrieval.knowledge.semantic_weight,
                "lexical_weight": runtime.retrieval.knowledge.lexical_weight,
                "chunk_size": runtime.retrieval.knowledge.chunk_size,
                "chunk_overlap": runtime.retrieval.knowledge.chunk_overlap,
            },
        },
        "tool_retry_guard": {
            "repeat_identical_failure_limit": runtime.tool_retry_guard.repeat_identical_failure_limit,
        },
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


def _runtime_from_payload(payload: dict[str, Any]) -> RuntimeConfig:
    tool_timeouts = payload.get("tool_timeouts", {})
    tool_output_limits = payload.get("tool_output_limits", {})
    autonomous_tools = payload.get("autonomous_tools", {})
    heartbeat = payload.get("heartbeat", {})
    cron = payload.get("cron", {})
    agent_runtime = payload.get("agent_runtime", {})
    llm_runtime = payload.get("llm_runtime", {})
    retrieval = payload.get("retrieval", {})
    memory_retrieval = retrieval.get("memory", {})
    knowledge_retrieval = retrieval.get("knowledge", {})
    tool_retry_guard = payload.get("tool_retry_guard", {})

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
        agent_runtime=AgentExecutionConfig(
            max_steps=max(1, int(agent_runtime.get("max_steps", 20))),
            max_retries=max(0, int(agent_runtime.get("max_retries", 1))),
        ),
        llm_runtime=LlmRuntimeConfig(
            temperature=float(llm_runtime.get("temperature", 0.2)),
            timeout_seconds=max(5, int(llm_runtime.get("timeout_seconds", 60))),
        ),
        retrieval=RetrievalConfig(
            memory=RetrievalDomainConfig(
                top_k=max(1, int(memory_retrieval.get("top_k", 3))),
                semantic_weight=float(memory_retrieval.get("semantic_weight", 0.7)),
                lexical_weight=float(memory_retrieval.get("lexical_weight", 0.3)),
                chunk_size=max(64, int(memory_retrieval.get("chunk_size", 256))),
                chunk_overlap=max(0, int(memory_retrieval.get("chunk_overlap", 32))),
            ),
            knowledge=RetrievalDomainConfig(
                top_k=max(1, int(knowledge_retrieval.get("top_k", 3))),
                semantic_weight=float(knowledge_retrieval.get("semantic_weight", 0.7)),
                lexical_weight=float(knowledge_retrieval.get("lexical_weight", 0.3)),
                chunk_size=max(64, int(knowledge_retrieval.get("chunk_size", 400))),
                chunk_overlap=max(0, int(knowledge_retrieval.get("chunk_overlap", 80))),
            ),
        ),
        tool_retry_guard=ToolRetryGuardConfig(
            repeat_identical_failure_limit=max(1, int(tool_retry_guard.get("repeat_identical_failure_limit", 2))),
        ),
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


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    if not config_path.exists():
        return RuntimeConfig()
    payload: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    return _runtime_from_payload(payload)


def merge_runtime_configs(base: RuntimeConfig, override: RuntimeConfig) -> RuntimeConfig:
    default_payload = _runtime_to_payload(RuntimeConfig())
    override_payload = _runtime_to_payload(override)
    override_delta = _deep_diff(override_payload, default_payload)
    merged_payload = _deep_merge(_runtime_to_payload(base), override_delta)
    return _runtime_from_payload(merged_payload)


def load_effective_runtime_config(global_config_path: Path, agent_config_path: Path) -> RuntimeConfig:
    global_payload: dict[str, Any] = {}
    agent_payload: dict[str, Any] = {}
    if global_config_path.exists():
        global_payload = json.loads(global_config_path.read_text(encoding="utf-8"))
    if agent_config_path.exists():
        agent_payload = json.loads(agent_config_path.read_text(encoding="utf-8"))
    merged_payload = _deep_merge(global_payload, agent_payload)
    return _runtime_from_payload(merged_payload)


def runtime_config_digest(runtime: RuntimeConfig) -> str:
    payload = _runtime_to_payload(runtime)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    runtime = load_runtime_config(base_dir / "config.json")
    secrets = _load_secrets()
    return AppConfig(base_dir=base_dir, runtime=runtime, secrets=secrets)


def save_runtime_config(base_dir: Path, runtime: RuntimeConfig) -> None:
    save_runtime_config_to_path(base_dir / "config.json", runtime)


def save_runtime_config_to_path(config_path: Path, runtime: RuntimeConfig) -> None:
    payload = _runtime_to_payload(runtime)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
