from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import dataclass
from typing import Any

from config import (
    AppConfig,
    LLMDriver,
    LLMProfile,
    LlmFallbackPolicy,
    LlmFallbackPolicyPatch,
    LlmRoutePatch,
    RuntimeConfig,
)


@dataclass(frozen=True)
class LlmProfileAvailability:
    available: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedLlmCandidate:
    profile_name: str
    profile: LLMProfile
    source: str


@dataclass(frozen=True)
class ResolvedLlmRoute:
    agent_id: str
    default_profile: str
    fallback_profiles: tuple[str, ...]
    fallback_policy: LlmFallbackPolicy
    tool_loop_model: str
    tool_loop_model_overrides: dict[str, str]
    candidates: tuple[ResolvedLlmCandidate, ...]
    valid: bool
    runnable: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "runnable": self.runnable,
            "default_profile": self.default_profile,
            "fallback_profiles": list(self.fallback_profiles),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _merge_fallback_policy(
    base: LlmFallbackPolicy, patch: LlmFallbackPolicyPatch | None
) -> LlmFallbackPolicy:
    if patch is None:
        return base
    return LlmFallbackPolicy(
        on_startup_missing_default=patch.on_startup_missing_default
        or base.on_startup_missing_default,
        on_runtime_auth_error=patch.on_runtime_auth_error
        or base.on_runtime_auth_error,
        on_timeout=patch.on_timeout or base.on_timeout,
        on_rate_limit=patch.on_rate_limit or base.on_rate_limit,
        on_5xx=patch.on_5xx or base.on_5xx,
        on_network_error=patch.on_network_error or base.on_network_error,
    )


def _effective_route_patch(
    *,
    agent_id: str,
    runtime: RuntimeConfig,
    config: AppConfig,
) -> tuple[str, list[str], LlmFallbackPolicy, str, dict[str, str]]:
    defaults = config.llm_defaults
    override = config.agent_llm_overrides.get(agent_id, LlmRoutePatch())
    workspace = runtime.llm

    default_profile = str(defaults.default or "").strip()
    if override.default is not None:
        default_profile = str(override.default).strip()
    if workspace.default is not None:
        default_profile = str(workspace.default).strip()
    if not default_profile:
        default_profile = config.default_llm_profile.strip()

    fallbacks = list(defaults.fallbacks or [])
    if override.fallbacks is not None:
        fallbacks = list(override.fallbacks)
    if workspace.fallbacks is not None:
        fallbacks = list(workspace.fallbacks)

    fallback_policy = LlmFallbackPolicy()
    fallback_policy = _merge_fallback_policy(
        fallback_policy, defaults.fallback_policy
    )
    fallback_policy = _merge_fallback_policy(
        fallback_policy, override.fallback_policy
    )
    fallback_policy = _merge_fallback_policy(
        fallback_policy, workspace.fallback_policy
    )
    tool_loop_model = (
        str(defaults.tool_loop_model).strip()
        if defaults.tool_loop_model is not None
        else ""
    )
    if override.tool_loop_model is not None:
        tool_loop_model = str(override.tool_loop_model).strip()
    if workspace.tool_loop_model is not None:
        tool_loop_model = str(workspace.tool_loop_model).strip()

    tool_loop_model_overrides = dict(defaults.tool_loop_model_overrides or {})
    if override.tool_loop_model_overrides is not None:
        tool_loop_model_overrides = dict(override.tool_loop_model_overrides)
    if workspace.tool_loop_model_overrides is not None:
        tool_loop_model_overrides = dict(workspace.tool_loop_model_overrides)
    return (
        default_profile,
        fallbacks,
        fallback_policy,
        tool_loop_model,
        tool_loop_model_overrides,
    )


def inspect_profile_availability(profile: LLMProfile) -> LlmProfileAvailability:
    reasons: list[str] = []
    if not profile.model.strip():
        reasons.append("missing model")
    env_key = profile.api_key_env.strip()
    if env_key and not (os.getenv(env_key, "") or "").strip():
        reasons.append(f"missing {env_key}")
    if (
        profile.driver == LLMDriver.OPENAI_COMPATIBLE
        and profile.provider_id != "openai"
        and not profile.base_url.strip()
    ):
        reasons.append("missing base_url")
    return LlmProfileAvailability(
        available=not reasons,
        reasons=tuple(reasons),
    )


def resolve_agent_llm_route(
    *,
    agent_id: str,
    runtime: RuntimeConfig,
    config: AppConfig,
) -> ResolvedLlmRoute:
    (
        default_profile_name,
        fallback_profiles,
        fallback_policy,
        tool_loop_model,
        tool_loop_model_overrides,
    ) = _effective_route_patch(agent_id=agent_id, runtime=runtime, config=config)

    warnings: list[str] = []
    errors: list[str] = []
    candidates: list[ResolvedLlmCandidate] = []

    if not default_profile_name:
        errors.append(f"Agent '{agent_id}' has no default LLM profile configured")
    elif default_profile_name not in config.llm_profiles:
        errors.append(
            f"Agent '{agent_id}' default profile '{default_profile_name}' is not defined"
        )
    else:
        default_profile = config.llm_profiles[default_profile_name]
        candidates.append(
            ResolvedLlmCandidate(
                profile_name=default_profile_name,
                profile=default_profile,
                source="default",
            )
        )

    seen_fallbacks: set[str] = set()
    for profile_name in fallback_profiles:
        normalized = str(profile_name).strip()
        if not normalized:
            continue
        if normalized == default_profile_name:
            errors.append(
                f"Agent '{agent_id}' fallback profile '{normalized}' duplicates the default"
            )
            continue
        if normalized in seen_fallbacks:
            errors.append(
                f"Agent '{agent_id}' fallback profile '{normalized}' is duplicated"
            )
            continue
        seen_fallbacks.add(normalized)
        profile = config.llm_profiles.get(normalized)
        if profile is None:
            errors.append(
                f"Agent '{agent_id}' fallback profile '{normalized}' is not defined"
            )
            continue
        candidates.append(
            ResolvedLlmCandidate(
                profile_name=normalized,
                profile=profile,
                source="fallback",
            )
        )

    valid = not errors
    runnable = valid

    if valid and default_profile_name:
        default_availability = inspect_profile_availability(
            config.llm_profiles[default_profile_name]
        )
        if not default_availability.available:
            runnable = False
            default_reason = ", ".join(default_availability.reasons)
            message = (
                f"Agent '{agent_id}' default profile '{default_profile_name}' is unavailable: "
                f"{default_reason}"
            )
            if fallback_policy.on_startup_missing_default == "error":
                errors.append(message)
                valid = False
            else:
                warnings.append(message)

    for candidate in candidates:
        if candidate.source != "fallback":
            continue
        availability = inspect_profile_availability(candidate.profile)
        if availability.available:
            continue
        warnings.append(
            f"Agent '{agent_id}' fallback profile '{candidate.profile_name}' will be skipped: "
            f"{', '.join(availability.reasons)}"
        )

    return ResolvedLlmRoute(
        agent_id=agent_id,
        default_profile=default_profile_name,
        fallback_profiles=tuple(fallback_profiles),
        fallback_policy=fallback_policy,
        tool_loop_model=tool_loop_model,
        tool_loop_model_overrides=dict(tool_loop_model_overrides),
        candidates=tuple(candidates),
        valid=valid,
        runnable=runnable,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def classify_llm_failure(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if isinstance(exc, (ConnectionError, socket.gaierror, OSError)):
        return "network_error"

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        if status_code in {401, 403}:
            return "auth_error"
        if status_code == 429:
            return "rate_limit"
        if 500 <= status_code < 600:
            return "5xx"

    class_name = exc.__class__.__name__.lower()
    text = str(exc).strip().lower()
    if "timeout" in class_name or "timed out" in text or "timeout" in text:
        return "timeout"
    if "rate" in class_name and "limit" in class_name:
        return "rate_limit"
    if any(
        token in class_name
        for token in ("authentication", "permission", "unauthorized", "forbidden")
    ):
        return "auth_error"
    if any(token in text for token in ("unauthorized", "forbidden", "invalid api key")):
        return "auth_error"
    if any(
        token in class_name
        for token in ("connection", "network", "transport", "dns")
    ):
        return "network_error"
    if any(token in text for token in ("connection", "network", "dns")):
        return "network_error"
    if any(token in text for token in ("status code 429", "too many requests")):
        return "rate_limit"
    if "5xx" in text or "status code 5" in text:
        return "5xx"
    return "other"


def should_fallback_for_error(
    policy: LlmFallbackPolicy,
    failure_kind: str,
) -> bool:
    if failure_kind == "auth_error":
        return policy.on_runtime_auth_error == "fallback"
    if failure_kind == "timeout":
        return policy.on_timeout == "fallback"
    if failure_kind == "rate_limit":
        return policy.on_rate_limit == "fallback"
    if failure_kind == "5xx":
        return policy.on_5xx == "fallback"
    if failure_kind == "network_error":
        return policy.on_network_error == "fallback"
    return False
