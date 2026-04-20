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
    OPENAI_COMPATIBLE = "openai_compatible"
    GOOGLE_AI_STUDIO = "google_ai_studio"


class LLMDriver(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"


class TerminalSandboxMode(str, Enum):
    HYBRID_AUTO = "hybrid_auto"
    DARWIN_SANDBOX = "darwin_sandbox"
    LINUX_BWRAP = "linux_bwrap"
    UNSAFE_NONE = "unsafe_none"


class TerminalCommandPolicyMode(str, Enum):
    AUTO = "auto"
    ALLOWLIST = "allowlist"
    DENYLIST = "denylist"


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
class LlmFallbackPolicy:
    on_startup_missing_default: str = "warn"
    on_runtime_auth_error: str = "fail"
    on_timeout: str = "fallback"
    on_rate_limit: str = "fallback"
    on_5xx: str = "fallback"
    on_network_error: str = "fallback"


@dataclass
class LlmFallbackPolicyPatch:
    on_startup_missing_default: str | None = None
    on_runtime_auth_error: str | None = None
    on_timeout: str | None = None
    on_rate_limit: str | None = None
    on_5xx: str | None = None
    on_network_error: str | None = None


@dataclass
class LlmRoutePatch:
    default: str | None = None
    fallbacks: list[str] | None = None
    fallback_policy: LlmFallbackPolicyPatch | None = None
    tool_loop_model: str | None = None
    tool_loop_model_overrides: dict[str, str] | None = None


@dataclass
class LLMProfile:
    profile_name: str
    provider_id: str
    driver: LLMDriver = LLMDriver.OPENAI_COMPATIBLE
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 60


@dataclass
class RetrievalDomainConfig:
    top_k: int = 3
    semantic_weight: float = 0.7
    lexical_weight: float = 0.3
    chunk_size: int = 256
    chunk_overlap: int = 32


@dataclass
class RetrievalStorageConfig:
    engine: str = "sqlite"
    db_path: str = "storage/retrieval.db"
    fts_prefilter_k: int = 50


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
    storage: RetrievalStorageConfig = field(default_factory=RetrievalStorageConfig)


@dataclass
class ToolRetryGuardConfig:
    repeat_identical_failure_limit: int = 2


@dataclass
class ToolNetworkConfig:
    allow_http_schemes: list[str] = field(default_factory=lambda: ["http", "https"])
    block_private_networks: bool = True
    max_redirects: int = 3
    max_content_bytes: int = 2_000_000


@dataclass
class TerminalExecutionConfig:
    sandbox_mode: TerminalSandboxMode = TerminalSandboxMode.HYBRID_AUTO
    command_policy_mode: TerminalCommandPolicyMode = TerminalCommandPolicyMode.AUTO
    require_sandbox: bool = True
    allowed_command_prefixes: list[str] = field(default_factory=list)
    denied_command_prefixes: list[str] = field(default_factory=list)
    allow_network: bool = False
    allow_shell_syntax: bool = False
    max_args: int = 32
    max_arg_length: int = 256


@dataclass
class ToolExecutionConfig:
    terminal: TerminalExecutionConfig = field(default_factory=TerminalExecutionConfig)


DEFAULT_CHAT_ENABLED_TOOLS: tuple[str, ...] = ()
DEFAULT_CHAT_BLOCKED_TOOLS: tuple[str, ...] = ()
DEFAULT_HEARTBEAT_ENABLED_TOOLS: tuple[str, ...] = ()
DEFAULT_CRON_ENABLED_TOOLS: tuple[str, ...] = (
    "web_search",
    "fetch_url",
    "read_files",
    "read_pdf",
    "search_knowledge_base",
    "sessions_list",
    "session_history",
    "agents_list",
    "scheduler_cron_jobs",
    "scheduler_cron_runs",
    "scheduler_heartbeat_status",
    "scheduler_heartbeat_runs",
)
DEFAULT_DELEGATION_ALLOWED_TOOL_SCOPES: dict[str, list[str]] = {
    "researcher": [
        "web_search",
        "fetch_url",
        "read_files",
        "search_knowledge_base",
    ],
    "analyst": [
        "read_files",
        "read_pdf",
        "search_knowledge_base",
        "terminal",
    ],
    "writer": ["read_files", "search_knowledge_base", "apply_patch"],
}
DEFAULT_DELEGATION_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_per_session": 5,
    "default_timeout_seconds": 120,
    "max_timeout_seconds": 600,
    "allowed_tool_scopes": DEFAULT_DELEGATION_ALLOWED_TOOL_SCOPES,
}


@dataclass
class AutonomousToolsConfig:
    heartbeat_enabled_tools: list[str] = field(
        default_factory=lambda: list(DEFAULT_HEARTBEAT_ENABLED_TOOLS)
    )
    cron_enabled_tools: list[str] = field(
        default_factory=lambda: list(DEFAULT_CRON_ENABLED_TOOLS)
    )


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
class SchedulerRuntimeConfig:
    api_enabled: bool = True
    runs_query_default_limit: int = 100


@dataclass
class HooksRuntimeConfig:
    enabled: bool = True
    default_timeout_ms: int = 10000


@dataclass
class DelegationConfig:
    enabled: bool = True
    max_per_session: int = 5
    default_timeout_seconds: int = 120
    max_timeout_seconds: int = 600
    allowed_tool_scopes: dict[str, list[str]] = field(
        default_factory=lambda: {
            role: [str(tool).strip() for tool in tools if str(tool).strip()]
            for role, tools in DEFAULT_DELEGATION_ALLOWED_TOOL_SCOPES.items()
        }
    )


@dataclass
class RuntimeConfig:
    rag_mode: bool = False
    injection_mode: InjectionMode = InjectionMode.EVERY_TURN
    bootstrap_max_chars: int = 20000
    bootstrap_total_max_chars: int = 150000
    agent_runtime: AgentExecutionConfig = field(default_factory=AgentExecutionConfig)
    llm_runtime: LlmRuntimeConfig = field(default_factory=LlmRuntimeConfig)
    llm: LlmRoutePatch = field(default_factory=LlmRoutePatch)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    tool_retry_guard: ToolRetryGuardConfig = field(default_factory=ToolRetryGuardConfig)
    tool_network: ToolNetworkConfig = field(default_factory=ToolNetworkConfig)
    tool_timeouts: ToolTimeouts = field(default_factory=ToolTimeouts)
    tool_output_limits: ToolOutputLimits = field(default_factory=ToolOutputLimits)
    tool_execution: ToolExecutionConfig = field(default_factory=ToolExecutionConfig)
    chat_enabled_tools: list[str] = field(
        default_factory=lambda: list(DEFAULT_CHAT_ENABLED_TOOLS)
    )
    chat_blocked_tools: list[str] = field(
        default_factory=lambda: list(DEFAULT_CHAT_BLOCKED_TOOLS)
    )
    autonomous_tools: AutonomousToolsConfig = field(
        default_factory=AutonomousToolsConfig
    )
    scheduler: SchedulerRuntimeConfig = field(default_factory=SchedulerRuntimeConfig)
    heartbeat: HeartbeatRuntimeConfig = field(default_factory=HeartbeatRuntimeConfig)
    cron: CronRuntimeConfig = field(default_factory=CronRuntimeConfig)
    hooks: HooksRuntimeConfig = field(default_factory=HooksRuntimeConfig)
    delegation: DelegationConfig = field(default_factory=DelegationConfig)


@dataclass
class SecretConfig:
    deepseek_api_key: str
    deepseek_base_url: str
    embedding_provider: EmbeddingProvider
    openai_api_key: str
    openai_base_url: str
    embedding_model: str
    google_api_key: str
    google_embedding_model: str
    embedding_api_key_env: str
    embedding_base_url: str
    embedding_default_headers: dict[str, str]


@dataclass
class AppConfig:
    base_dir: Path
    runtime: RuntimeConfig
    secrets: SecretConfig
    llm_profiles: dict[str, LLMProfile]
    llm_defaults: LlmRoutePatch
    agent_llm_overrides: dict[str, LlmRoutePatch]
    default_llm_profile: str


from utils.dict_ops import deep_merge as _deep_merge, deep_diff as _deep_diff


_LLM_ROUTE_KEYS = {
    "default",
    "fallbacks",
    "fallback_policy",
    "tool_loop_model",
    "tool_loop_model_overrides",
}
_LLM_FALLBACK_POLICY_KEYS = {
    "on_startup_missing_default",
    "on_runtime_auth_error",
    "on_timeout",
    "on_rate_limit",
    "on_5xx",
    "on_network_error",
}
_STARTUP_POLICY_VALUES = {"warn", "error"}
_RUNTIME_FALLBACK_POLICY_VALUES = {"fail", "fallback"}


def _validate_delegation_config(config: dict[str, Any]) -> list[str] | None:
    errors: list[str] = []

    max_per = config.get("max_per_session", 5)
    if not isinstance(max_per, int) or max_per < 1:
        errors.append("max_per_session must be >= 1")

    default_timeout = config.get("default_timeout_seconds", 120)
    if not isinstance(default_timeout, int) or default_timeout < 1:
        errors.append("default_timeout_seconds must be >= 1")

    max_timeout = config.get("max_timeout_seconds", 600)
    if not isinstance(max_timeout, int) or max_timeout < 1:
        errors.append("max_timeout_seconds must be >= 1")

    if (
        isinstance(default_timeout, int)
        and isinstance(max_timeout, int)
        and default_timeout > max_timeout
    ):
        errors.append("default_timeout_seconds must be <= max_timeout_seconds")

    scopes = config.get("allowed_tool_scopes", {})
    if not isinstance(scopes, dict) or not scopes:
        errors.append("allowed_tool_scopes must be a non-empty dict")
    else:
        for role, tools in scopes.items():
            if not isinstance(tools, list) or not tools:
                errors.append(f"scope '{role}' must be a non-empty list")
            if "delegate" in tools:
                errors.append(
                    f"scope '{role}' cannot include 'delegate' (nested delegation blocked)"
                )

    return errors if errors else None


def _llm_fallback_policy_to_payload(
    policy: LlmFallbackPolicyPatch | None,
) -> dict[str, str]:
    if policy is None:
        return {}
    payload: dict[str, str] = {}
    for key in sorted(_LLM_FALLBACK_POLICY_KEYS):
        value = getattr(policy, key, None)
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized:
            payload[key] = normalized
    return payload


def _llm_route_to_payload(route: LlmRoutePatch) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    default_profile = str(route.default or "").strip()
    if default_profile:
        payload["default"] = default_profile
    if route.fallbacks is not None:
        payload["fallbacks"] = [str(item).strip() for item in route.fallbacks]
    fallback_policy = _llm_fallback_policy_to_payload(route.fallback_policy)
    if fallback_policy:
        payload["fallback_policy"] = fallback_policy
    if route.tool_loop_model is not None:
        payload["tool_loop_model"] = str(route.tool_loop_model).strip()
    if route.tool_loop_model_overrides is not None:
        payload["tool_loop_model_overrides"] = {
            str(source).strip(): str(target).strip()
            for source, target in route.tool_loop_model_overrides.items()
            if str(source).strip() and str(target).strip()
        }
    return payload


def _parse_tool_loop_model_overrides(
    value: Any,
    *,
    strict: bool,
    context: str,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise ValueError(f"{context} must be an object")
        return {}
    overrides: dict[str, str] = {}
    for raw_source, raw_target in value.items():
        source = str(raw_source).strip().lower()
        target = str(raw_target).strip()
        if not source or not target:
            continue
        overrides[source] = target
    return overrides


def _parse_llm_fallback_policy_patch(
    value: Any,
    *,
    strict: bool,
    context: str,
) -> LlmFallbackPolicyPatch:
    if value is None:
        return LlmFallbackPolicyPatch()
    if not isinstance(value, dict):
        if strict:
            raise ValueError(f"{context} must be an object")
        return LlmFallbackPolicyPatch()
    if strict:
        unknown = sorted(set(value.keys()) - _LLM_FALLBACK_POLICY_KEYS)
        if unknown:
            raise ValueError(
                f"{context} has unknown keys: {', '.join(unknown)}"
            )

    def _normalize_policy_value(
        key: str,
        allowed: set[str],
    ) -> str | None:
        if key not in value:
            return None
        normalized = str(value.get(key, "")).strip().lower()
        if not normalized:
            return None
        if strict and normalized not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise ValueError(
                f"{context}.{key} must be one of: {allowed_values}"
            )
        if normalized in allowed:
            return normalized
        return None

    return LlmFallbackPolicyPatch(
        on_startup_missing_default=_normalize_policy_value(
            "on_startup_missing_default", _STARTUP_POLICY_VALUES
        ),
        on_runtime_auth_error=_normalize_policy_value(
            "on_runtime_auth_error", _RUNTIME_FALLBACK_POLICY_VALUES
        ),
        on_timeout=_normalize_policy_value(
            "on_timeout", _RUNTIME_FALLBACK_POLICY_VALUES
        ),
        on_rate_limit=_normalize_policy_value(
            "on_rate_limit", _RUNTIME_FALLBACK_POLICY_VALUES
        ),
        on_5xx=_normalize_policy_value("on_5xx", _RUNTIME_FALLBACK_POLICY_VALUES),
        on_network_error=_normalize_policy_value(
            "on_network_error", _RUNTIME_FALLBACK_POLICY_VALUES
        ),
    )


def _parse_llm_route_patch(
    value: Any,
    *,
    strict: bool,
    context: str,
) -> LlmRoutePatch:
    if value is None:
        return LlmRoutePatch()
    if not isinstance(value, dict):
        if strict:
            raise ValueError(f"{context} must be an object")
        return LlmRoutePatch()
    if strict:
        unknown = sorted(set(value.keys()) - _LLM_ROUTE_KEYS)
        if unknown:
            raise ValueError(
                f"{context} has unknown keys: {', '.join(unknown)}"
            )

    default_profile: str | None = None
    if "default" in value:
        default_profile = str(value.get("default", "")).strip() or None
        if strict and default_profile is None:
            raise ValueError(f"{context}.default must be a non-empty string")

    fallbacks: list[str] | None = None
    if "fallbacks" in value:
        raw_fallbacks = value.get("fallbacks")
        if not isinstance(raw_fallbacks, list):
            if strict:
                raise ValueError(f"{context}.fallbacks must be an array")
            raw_fallbacks = []
        fallbacks = []
        for item in raw_fallbacks:
            profile_id = str(item).strip()
            if profile_id:
                fallbacks.append(profile_id)

    fallback_policy: LlmFallbackPolicyPatch | None = None
    if "fallback_policy" in value:
        fallback_policy = _parse_llm_fallback_policy_patch(
            value.get("fallback_policy"),
            strict=strict,
            context=f"{context}.fallback_policy",
        )

    tool_loop_model: str | None = None
    if "tool_loop_model" in value:
        tool_loop_model = str(value.get("tool_loop_model", "")).strip()

    tool_loop_model_overrides: dict[str, str] | None = None
    if "tool_loop_model_overrides" in value:
        tool_loop_model_overrides = _parse_tool_loop_model_overrides(
            value.get("tool_loop_model_overrides"),
            strict=strict,
            context=f"{context}.tool_loop_model_overrides",
        )

    return LlmRoutePatch(
        default=default_profile,
        fallbacks=fallbacks,
        fallback_policy=fallback_policy,
        tool_loop_model=tool_loop_model,
        tool_loop_model_overrides=tool_loop_model_overrides,
    )


def _parse_agent_llm_overrides(value: Any) -> dict[str, LlmRoutePatch]:
    if not isinstance(value, dict):
        return {}
    overrides: dict[str, LlmRoutePatch] = {}
    for raw_agent_id, raw_route in value.items():
        agent_id = str(raw_agent_id).strip()
        if not agent_id:
            continue
        overrides[agent_id] = _parse_llm_route_patch(
            raw_route,
            strict=False,
            context=f"agent_llm_overrides.{agent_id}",
        )
    return overrides


def _runtime_to_payload(runtime: RuntimeConfig) -> dict[str, Any]:
    sandbox_mode = runtime.tool_execution.terminal.sandbox_mode
    sandbox_mode_value = (
        sandbox_mode.value
        if isinstance(sandbox_mode, TerminalSandboxMode)
        else (str(sandbox_mode).strip() or TerminalSandboxMode.HYBRID_AUTO.value)
    )
    command_policy_mode = runtime.tool_execution.terminal.command_policy_mode
    command_policy_mode_value = (
        command_policy_mode.value
        if isinstance(command_policy_mode, TerminalCommandPolicyMode)
        else (
            str(command_policy_mode).strip()
            or TerminalCommandPolicyMode.AUTO.value
        )
    )
    payload = {
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
            "storage": {
                "engine": runtime.retrieval.storage.engine,
                "db_path": runtime.retrieval.storage.db_path,
                "fts_prefilter_k": runtime.retrieval.storage.fts_prefilter_k,
            },
        },
        "tool_retry_guard": {
            "repeat_identical_failure_limit": runtime.tool_retry_guard.repeat_identical_failure_limit,
        },
        "tool_network": {
            "allow_http_schemes": list(runtime.tool_network.allow_http_schemes),
            "block_private_networks": runtime.tool_network.block_private_networks,
            "max_redirects": runtime.tool_network.max_redirects,
            "max_content_bytes": runtime.tool_network.max_content_bytes,
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
        "tool_execution": {
            "terminal": {
                "sandbox_mode": sandbox_mode_value,
                "command_policy_mode": command_policy_mode_value,
                "require_sandbox": runtime.tool_execution.terminal.require_sandbox,
                "allowed_command_prefixes": list(
                    runtime.tool_execution.terminal.allowed_command_prefixes
                ),
                "denied_command_prefixes": list(
                    runtime.tool_execution.terminal.denied_command_prefixes
                ),
                "allow_network": runtime.tool_execution.terminal.allow_network,
                "allow_shell_syntax": runtime.tool_execution.terminal.allow_shell_syntax,
                "max_args": runtime.tool_execution.terminal.max_args,
                "max_arg_length": runtime.tool_execution.terminal.max_arg_length,
            }
        },
        "chat_enabled_tools": list(runtime.chat_enabled_tools),
        "chat_blocked_tools": list(runtime.chat_blocked_tools),
        "autonomous_tools": {
            "heartbeat_enabled_tools": list(
                runtime.autonomous_tools.heartbeat_enabled_tools
            ),
            "cron_enabled_tools": list(runtime.autonomous_tools.cron_enabled_tools),
        },
        "scheduler": {
            "api_enabled": runtime.scheduler.api_enabled,
            "runs_query_default_limit": runtime.scheduler.runs_query_default_limit,
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
        "hooks": {
            "enabled": runtime.hooks.enabled,
            "default_timeout_ms": runtime.hooks.default_timeout_ms,
        },
        "delegation": {
            "enabled": runtime.delegation.enabled,
            "max_per_session": runtime.delegation.max_per_session,
            "default_timeout_seconds": runtime.delegation.default_timeout_seconds,
            "max_timeout_seconds": runtime.delegation.max_timeout_seconds,
            "allowed_tool_scopes": {
                str(role).strip(): [
                    str(tool).strip()
                    for tool in tools
                    if str(tool).strip()
                ]
                for role, tools in runtime.delegation.allowed_tool_scopes.items()
                if str(role).strip()
            },
        },
    }
    llm_payload = _llm_route_to_payload(runtime.llm)
    if llm_payload:
        payload["llm"] = llm_payload
    return payload


def _runtime_from_payload(
    payload: dict[str, Any], *, strict: bool = False
) -> RuntimeConfig:
    tool_timeouts = payload.get("tool_timeouts", {})
    tool_output_limits = payload.get("tool_output_limits", {})
    autonomous_tools = payload.get("autonomous_tools", {})
    heartbeat = payload.get("heartbeat", {})
    cron = payload.get("cron", {})
    agent_runtime = payload.get("agent_runtime", {})
    llm_runtime = payload.get("llm_runtime", {})
    llm_route = payload.get("llm", {})
    retrieval = payload.get("retrieval", {})
    memory_retrieval = retrieval.get("memory", {})
    knowledge_retrieval = retrieval.get("knowledge", {})
    storage_retrieval = retrieval.get("storage", {})
    tool_retry_guard = payload.get("tool_retry_guard", {})
    tool_network = payload.get("tool_network", {})
    tool_execution = payload.get("tool_execution", {})
    terminal_execution = {}
    if isinstance(tool_execution, dict):
        maybe_terminal = tool_execution.get("terminal", {})
        if isinstance(maybe_terminal, dict):
            terminal_execution = maybe_terminal
    scheduler = payload.get("scheduler", {})
    hooks = payload.get("hooks", {})
    delegation = payload.get("delegation", {})

    injection_value = payload.get("injection_mode", InjectionMode.EVERY_TURN.value)
    try:
        injection_mode = InjectionMode(injection_value)
    except ValueError:
        injection_mode = InjectionMode.EVERY_TURN

    def _normalized_tool_list(
        value: Any, fallback: tuple[str, ...], *, fallback_on_empty: bool = False
    ) -> list[str]:
        if not isinstance(value, list):
            return list(fallback)
        normalized: list[str] = []
        for item in value:
            tool_name = str(item).strip()
            if not tool_name or tool_name in normalized:
                continue
            normalized.append(tool_name)
        if not normalized and fallback_on_empty:
            return list(fallback)
        return normalized

    def _terminal_sandbox_mode(value: Any) -> TerminalSandboxMode:
        raw = str(value).strip().lower() or TerminalSandboxMode.HYBRID_AUTO.value
        try:
            return TerminalSandboxMode(raw)
        except ValueError:
            return TerminalSandboxMode.HYBRID_AUTO

    def _terminal_command_policy_mode(
        value: Any,
        *,
        has_allowed_prefix_field: bool,
        is_explicit: bool,
    ) -> TerminalCommandPolicyMode:
        if is_explicit:
            raw = (
                str(value).strip().lower()
                or TerminalCommandPolicyMode.AUTO.value
            )
            try:
                return TerminalCommandPolicyMode(raw)
            except ValueError:
                return TerminalCommandPolicyMode.AUTO
        if has_allowed_prefix_field:
            return TerminalCommandPolicyMode.ALLOWLIST
        return TerminalCommandPolicyMode.AUTO

    if strict and isinstance(llm_runtime, dict) and "profile" in llm_runtime:
        raise ValueError(
            "llm_runtime.profile is no longer supported; use llm.default and llm.fallbacks"
        )

    delegation_payload = DEFAULT_DELEGATION_CONFIG | (
        delegation if isinstance(delegation, dict) else {}
    )
    if strict:
        errors = _validate_delegation_config(delegation_payload)
        if errors:
            raise ValueError("; ".join(errors))
    allowed_tool_scopes: dict[str, list[str]] = {}
    raw_scopes = delegation_payload.get("allowed_tool_scopes", {})
    if isinstance(raw_scopes, dict):
        for raw_role, raw_tools in raw_scopes.items():
            role = str(raw_role).strip()
            if not role or not isinstance(raw_tools, list):
                continue
            tools: list[str] = []
            for item in raw_tools:
                tool_name = str(item).strip()
                if tool_name and tool_name not in tools:
                    tools.append(tool_name)
            if tools:
                allowed_tool_scopes[role] = tools

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
        llm=_parse_llm_route_patch(llm_route, strict=strict, context="llm"),
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
            storage=RetrievalStorageConfig(
                engine=str(storage_retrieval.get("engine", "sqlite")).strip().lower()
                or "sqlite",
                db_path=str(
                    storage_retrieval.get("db_path", "storage/retrieval.db")
                ).strip()
                or "storage/retrieval.db",
                fts_prefilter_k=max(
                    1, int(storage_retrieval.get("fts_prefilter_k", 50))
                ),
            ),
        ),
        tool_retry_guard=ToolRetryGuardConfig(
            repeat_identical_failure_limit=max(
                1, int(tool_retry_guard.get("repeat_identical_failure_limit", 2))
            ),
        ),
        tool_network=ToolNetworkConfig(
            allow_http_schemes=[
                str(item).strip().lower()
                for item in list(
                    tool_network.get("allow_http_schemes", ["http", "https"])
                )
                if str(item).strip()
            ]
            or ["http", "https"],
            block_private_networks=bool(
                tool_network.get("block_private_networks", True)
            ),
            max_redirects=max(0, int(tool_network.get("max_redirects", 3))),
            max_content_bytes=max(
                1024, int(tool_network.get("max_content_bytes", 2_000_000))
            ),
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
        tool_execution=ToolExecutionConfig(
            terminal=TerminalExecutionConfig(
                sandbox_mode=_terminal_sandbox_mode(
                    terminal_execution.get(
                        "sandbox_mode", TerminalSandboxMode.HYBRID_AUTO.value
                    )
                ),
                command_policy_mode=_terminal_command_policy_mode(
                    terminal_execution.get("command_policy_mode"),
                    has_allowed_prefix_field=(
                        "allowed_command_prefixes" in terminal_execution
                    ),
                    is_explicit="command_policy_mode" in terminal_execution,
                ),
                require_sandbox=bool(terminal_execution.get("require_sandbox", True)),
                allowed_command_prefixes=_normalized_tool_list(
                    terminal_execution.get("allowed_command_prefixes"),
                    (),
                ),
                denied_command_prefixes=_normalized_tool_list(
                    terminal_execution.get("denied_command_prefixes"),
                    (),
                ),
                allow_network=bool(terminal_execution.get("allow_network", False)),
                allow_shell_syntax=bool(
                    terminal_execution.get("allow_shell_syntax", False)
                ),
                max_args=max(1, int(terminal_execution.get("max_args", 32))),
                max_arg_length=max(
                    16, int(terminal_execution.get("max_arg_length", 256))
                ),
            )
        ),
        chat_enabled_tools=_normalized_tool_list(
            payload.get("chat_enabled_tools"),
            DEFAULT_CHAT_ENABLED_TOOLS,
        ),
        chat_blocked_tools=_normalized_tool_list(
            payload.get("chat_blocked_tools"),
            DEFAULT_CHAT_BLOCKED_TOOLS,
        ),
        autonomous_tools=AutonomousToolsConfig(
            heartbeat_enabled_tools=_normalized_tool_list(
                autonomous_tools.get("heartbeat_enabled_tools"),
                DEFAULT_HEARTBEAT_ENABLED_TOOLS,
            ),
            cron_enabled_tools=_normalized_tool_list(
                autonomous_tools.get("cron_enabled_tools"),
                DEFAULT_CRON_ENABLED_TOOLS,
            ),
        ),
        scheduler=SchedulerRuntimeConfig(
            api_enabled=bool(scheduler.get("api_enabled", True)),
            runs_query_default_limit=max(
                1, int(scheduler.get("runs_query_default_limit", 100))
            ),
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
        hooks=HooksRuntimeConfig(
            enabled=bool(hooks.get("enabled", True)),
            default_timeout_ms=max(100, int(hooks.get("default_timeout_ms", 10000))),
        ),
        delegation=DelegationConfig(
            enabled=bool(delegation_payload.get("enabled", True)),
            max_per_session=max(1, int(delegation_payload.get("max_per_session", 5))),
            default_timeout_seconds=max(
                1, int(delegation_payload.get("default_timeout_seconds", 120))
            ),
            max_timeout_seconds=max(
                1, int(delegation_payload.get("max_timeout_seconds", 600))
            ),
            allowed_tool_scopes=allowed_tool_scopes
            or {
                role: list(tools)
                for role, tools in DEFAULT_DELEGATION_ALLOWED_TOOL_SCOPES.items()
            },
        ),
    )


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    if not config_path.exists():
        return RuntimeConfig()
    payload: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    return _runtime_from_payload(payload, strict=False)


def merge_runtime_configs(
    base: RuntimeConfig, override: RuntimeConfig
) -> RuntimeConfig:
    default_payload = _runtime_to_payload(RuntimeConfig())
    override_payload = _runtime_to_payload(override)
    override_delta = _deep_diff(override_payload, default_payload)
    merged_payload = _deep_merge(_runtime_to_payload(base), override_delta)
    return _runtime_from_payload(merged_payload)


def load_effective_runtime_config(
    global_config_path: Path, agent_config_path: Path
) -> RuntimeConfig:
    global_payload: dict[str, Any] = {}
    agent_payload: dict[str, Any] = {}
    if global_config_path.exists():
        global_payload = json.loads(global_config_path.read_text(encoding="utf-8"))
    if agent_config_path.exists():
        agent_payload = json.loads(agent_config_path.read_text(encoding="utf-8"))
    merged_payload = _deep_merge(global_payload, agent_payload)
    return _runtime_from_payload(merged_payload, strict=False)


def runtime_config_digest(runtime: RuntimeConfig) -> str:
    payload = _runtime_to_payload(runtime)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def runtime_to_payload(runtime: RuntimeConfig) -> dict[str, Any]:
    return _runtime_to_payload(runtime)


def runtime_from_payload(payload: dict[str, Any]) -> RuntimeConfig:
    return _runtime_from_payload(payload, strict=True)


def _parse_headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for key, item in value.items():
            header_name = str(key).strip()
            header_value = str(item).strip()
            if header_name and header_value:
                result[header_name] = header_value
        return result
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return _parse_headers(parsed)
    return {}


def resolve_header_templates(headers: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in headers.items():
        candidate = str(value)
        if candidate.startswith("${ENV:") and candidate.endswith("}"):
            env_key = candidate[len("${ENV:") : -1].strip()
            resolved_value = os.getenv(env_key, "")
            if resolved_value:
                resolved[key] = resolved_value
            continue
        resolved[key] = candidate
    return resolved


def _coerce_llm_profile(name: str, payload: dict[str, Any]) -> LLMProfile:
    driver_raw = str(payload.get("driver", LLMDriver.OPENAI_COMPATIBLE.value)).strip()
    try:
        driver = LLMDriver(driver_raw)
    except ValueError:
        driver = LLMDriver.OPENAI_COMPATIBLE
    return LLMProfile(
        profile_name=name,
        provider_id=str(payload.get("provider_id", "unknown")).strip().lower()
        or "unknown",
        driver=driver,
        base_url=str(payload.get("base_url", "")).strip(),
        model=str(payload.get("model", "")).strip(),
        api_key_env=str(payload.get("api_key_env", "")).strip(),
        default_headers=_parse_headers(payload.get("default_headers", {})),
        timeout_seconds=max(5, int(payload.get("timeout_seconds", 60))),
    )


def _looks_like_profile_group(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("models"), dict)


def _coerce_group_model_payload(
    *,
    provider_key: str,
    provider_payload: dict[str, Any],
    model_key: str,
    model_payload: Any,
) -> dict[str, Any] | None:
    shared_payload = {
        "provider_id": str(
            provider_payload.get("provider_id", provider_key)
        ).strip().lower()
        or provider_key.lower(),
        "driver": provider_payload.get("driver", LLMDriver.OPENAI_COMPATIBLE.value),
        "base_url": provider_payload.get("base_url", ""),
        "api_key_env": provider_payload.get("api_key_env", ""),
        "default_headers": _parse_headers(provider_payload.get("default_headers", {})),
        "timeout_seconds": provider_payload.get("timeout_seconds", 60),
    }
    if isinstance(model_payload, str):
        return {
            **shared_payload,
            "model": model_payload,
        }
    if isinstance(model_payload, dict):
        merged_payload = _deep_merge(shared_payload, model_payload)
        if not str(merged_payload.get("model", "")).strip():
            return None
        return merged_payload
    return None


def _default_llm_profiles() -> dict[str, LLMProfile]:
    azure_api_env = (
        os.getenv("AZURE_FOUNDRY_API_KEY_ENV", "AZURE_FOUNDRY_API_KEY").strip()
        or "AZURE_FOUNDRY_API_KEY"
    )
    azure_headers = _parse_headers(os.getenv("AZURE_FOUNDRY_DEFAULT_HEADERS_JSON", ""))
    if not azure_headers:
        auth_header = (
            os.getenv("AZURE_FOUNDRY_AUTH_HEADER", "api-key").strip() or "api-key"
        )
        azure_headers = {auth_header: f"${{ENV:{azure_api_env}}}"}

    profiles = {
        "deepseek": LLMProfile(
            profile_name="deepseek",
            provider_id="deepseek",
            driver=LLMDriver.OPENAI_COMPATIBLE,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model="deepseek-chat",
            api_key_env="DEEPSEEK_API_KEY",
            default_headers={},
            timeout_seconds=max(5, int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))),
        ),
        "openai": LLMProfile(
            profile_name="openai",
            provider_id="openai",
            driver=LLMDriver.OPENAI_COMPATIBLE,
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model="gpt-4o-mini",
            api_key_env="OPENAI_API_KEY",
            default_headers={},
            timeout_seconds=max(5, int(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))),
        ),
        "azure_foundry": LLMProfile(
            profile_name="azure_foundry",
            provider_id="azure_foundry",
            driver=LLMDriver.OPENAI_COMPATIBLE,
            base_url=os.getenv("AZURE_FOUNDRY_BASE_URL", ""),
            model="gpt-4.1-mini",
            api_key_env=azure_api_env,
            default_headers=azure_headers,
            timeout_seconds=max(
                5, int(os.getenv("AZURE_FOUNDRY_TIMEOUT_SECONDS", "60"))
            ),
        ),
    }
    return profiles


def _merge_llm_profiles(
    *,
    base_profiles: dict[str, LLMProfile],
    payload: Any,
) -> dict[str, LLMProfile]:
    merged = dict(base_profiles)
    source: dict[str, Any] = {}
    if isinstance(payload, dict):
        source = payload
    elif isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("profile_name", "")).strip()
            if name:
                source[name] = item
    elif isinstance(payload, str):
        raw = payload.strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
            return _merge_llm_profiles(base_profiles=merged, payload=parsed)

    for name, item in source.items():
        profile_name = str(name).strip()
        if not profile_name:
            continue
        if _looks_like_profile_group(item):
            provider_payload = item
            models = provider_payload.get("models", {})
            assert isinstance(models, dict)
            for model_name, model_payload in models.items():
                model_key = str(model_name).strip()
                if not model_key:
                    continue
                expanded = _coerce_group_model_payload(
                    provider_key=profile_name,
                    provider_payload=provider_payload,
                    model_key=model_key,
                    model_payload=model_payload,
                )
                if expanded is None:
                    continue
                merged[f"{profile_name}.{model_key}"] = _coerce_llm_profile(
                    f"{profile_name}.{model_key}",
                    expanded,
                )
            continue
        if not isinstance(item, dict):
            continue
        merged[profile_name] = _coerce_llm_profile(profile_name, item)
    return merged


def _load_secrets() -> SecretConfig:
    provider_raw = os.getenv("EMBEDDING_PROVIDER", EmbeddingProvider.OPENAI.value)
    try:
        embedding_provider = EmbeddingProvider(provider_raw)
    except ValueError:
        embedding_provider = EmbeddingProvider.OPENAI

    return SecretConfig(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        embedding_provider=embedding_provider,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_embedding_model=os.getenv(
            "GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"
        ),
        embedding_api_key_env=os.getenv(
            "EMBEDDING_API_KEY_ENV", os.getenv("OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
        ),
        embedding_base_url=os.getenv(
            "EMBEDDING_BASE_URL",
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ),
        embedding_default_headers=_parse_headers(
            os.getenv("EMBEDDING_DEFAULT_HEADERS_JSON", "")
        ),
    )


def validate_required_secrets(config: AppConfig) -> list[str]:
    missing: list[str] = []
    if not (os.getenv("APP_ADMIN_TOKEN", "") or "").strip():
        missing.append("APP_ADMIN_TOKEN")
    return missing


def load_config(base_dir: Path) -> AppConfig:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=base_dir / ".env", override=False)
    config_path = base_dir / "config.json"
    runtime = load_runtime_config(config_path)
    secrets = _load_secrets()
    raw_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw_config = raw
        except Exception:
            raw_config = {}

    llm_profiles = _default_llm_profiles()
    llm_profiles = _merge_llm_profiles(
        base_profiles=llm_profiles, payload=raw_config.get("llm_profiles")
    )

    default_llm_profile = (
        str(raw_config.get("default_llm_profile", "")).strip()
        or (os.getenv("DEFAULT_LLM_PROFILE", "") or "").strip()
        or "deepseek"
    )
    if default_llm_profile not in llm_profiles and llm_profiles:
        default_llm_profile = sorted(llm_profiles.keys())[0]

    return AppConfig(
        base_dir=base_dir,
        runtime=runtime,
        secrets=secrets,
        llm_profiles=llm_profiles,
        llm_defaults=_parse_llm_route_patch(
            raw_config.get("llm_defaults"),
            strict=False,
            context="llm_defaults",
        ),
        agent_llm_overrides=_parse_agent_llm_overrides(
            raw_config.get("agent_llm_overrides")
        ),
        default_llm_profile=default_llm_profile,
    )


def save_runtime_config(base_dir: Path, runtime: RuntimeConfig) -> None:
    save_runtime_config_to_path(base_dir / "config.json", runtime)


def save_runtime_config_to_path(config_path: Path, runtime: RuntimeConfig) -> None:
    payload = _runtime_to_payload(runtime)
    merged_payload: dict[str, Any] = dict(payload)
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                for key, value in existing.items():
                    if key not in payload:
                        merged_payload[key] = value
        except Exception:
            merged_payload = dict(payload)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(merged_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(config_path)
