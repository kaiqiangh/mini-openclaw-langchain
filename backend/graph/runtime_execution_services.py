from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, cast

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import AppConfig, LLMProfile, RuntimeConfig, resolve_header_templates
from graph.callbacks import AuditCallbackHandler, UsageCaptureCallbackHandler
from graph.prompt_builder import PromptBuilder
from graph.runtime_types import ToolCapableChatModel
from graph.usage_orchestrator import UsageOrchestrator
from tools.delegate_registry import DelegateRegistry
from tools.delegate_tool import build_delegate_tool, build_delegate_status_tool
from llm_routing import (
    ResolvedLlmCandidate,
    ResolvedLlmRoute,
    inspect_profile_availability,
    resolve_agent_llm_route,
)
from observability.tracing import build_optional_callbacks
from tools.skills_scanner import ensure_skills_snapshot
from usage.pricing import infer_provider


class SessionRepositoryHandle(Protocol):
    pass


class RuntimeWithServices(Protocol):
    agent_id: str
    root_dir: Path
    runtime_config: RuntimeConfig
    llm_cache: dict[tuple[Any, ...], ToolCapableChatModel]
    audit_store: Any


@dataclass(frozen=True)
class RuntimeCallbackBundle:
    callbacks: list[Any]
    usage_capture: UsageCaptureCallbackHandler


class RuntimeExecutionServices:
    def __init__(
        self,
        *,
        base_dir_getter: Callable[[], Path | None],
        app_config_getter: Callable[[], AppConfig],
        runtime_getter: Callable[[str], RuntimeWithServices],
        prompt_builder: PromptBuilder,
        usage_orchestrator: UsageOrchestrator,
        delegate_registry: DelegateRegistry | None = None,
        agent_manager: Any | None = None,
    ) -> None:
        self._base_dir_getter = base_dir_getter
        self._app_config_getter = app_config_getter
        self._runtime_getter = runtime_getter
        self.prompt_builder = prompt_builder
        self.usage_orchestrator = usage_orchestrator
        self.session_repository: SessionRepositoryHandle | None = None
        self.delegate_registry = delegate_registry
        self._agent_manager = agent_manager

    def set_session_repository(self, repository: SessionRepositoryHandle) -> None:
        self.session_repository = repository

    def require_session_repository(self) -> SessionRepositoryHandle:
        if self.session_repository is None:
            raise RuntimeError("Session repository is not configured")
        return self.session_repository

    def get_runtime(self, agent_id: str = "default") -> RuntimeWithServices:
        return self._runtime_getter(agent_id)

    def get_app_config(self) -> AppConfig:
        return self._app_config_getter()

    def require_base_dir(self) -> Path:
        base_dir = self._base_dir_getter()
        if base_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        return base_dir

    def build_system_prompt(
        self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default"
    ) -> str:
        runtime = self.get_runtime(agent_id)
        ensure_skills_snapshot(runtime.root_dir)
        pack = self.prompt_builder.build_system_prompt(
            base_dir=runtime.root_dir,
            runtime=runtime.runtime_config,
            rag_mode=rag_mode,
            is_first_turn=is_first_turn,
        )
        return pack.prompt

    @staticmethod
    def _profile_api_key(profile: LLMProfile) -> str:
        env_key = profile.api_key_env.strip()
        if not env_key:
            return ""
        return (os.getenv(env_key, "") or "").strip()

    def build_llm_kwargs(
        self,
        *,
        profile: LLMProfile,
        runtime: RuntimeConfig,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        model = (model_override or profile.model or "").strip()
        if not model:
            raise RuntimeError(
                f"LLM profile '{profile.profile_name}' has no model configured"
            )
        api_key = self._profile_api_key(profile)
        if not api_key:
            missing_env = profile.api_key_env.strip() or "API_KEY"
            raise RuntimeError(f"{missing_env} is not configured")

        effective_timeout = max(
            5, int(runtime.llm_runtime.timeout_seconds or profile.timeout_seconds or 60)
        )
        headers = resolve_header_templates(dict(profile.default_headers))
        normalized_header_keys = {key.lower() for key in headers}
        if (
            "authorization" not in normalized_header_keys
            and "api-key" not in normalized_header_keys
            and "x-api-key" not in normalized_header_keys
        ):
            headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")

        llm_kwargs: dict[str, Any] = {
            "model": model,
            "api_key": SecretStr(api_key),
            "temperature": runtime.llm_runtime.temperature,
            "timeout": effective_timeout,
        }
        if profile.base_url.strip():
            llm_kwargs["base_url"] = profile.base_url.strip()
        if headers:
            llm_kwargs["default_headers"] = headers
        return llm_kwargs

    @staticmethod
    def _tool_loop_override_is_compatible(
        *,
        configured_model: str,
        target_model: str,
        provider_id: str = "",
        base_url: str = "",
    ) -> bool:
        configured_provider = infer_provider(
            configured_model,
            base_url=base_url,
            explicit_provider=provider_id,
        )
        target_provider = infer_provider(target_model)
        if (
            configured_provider != "unknown"
            and target_provider != "unknown"
            and configured_provider != target_provider
        ):
            return False
        return True

    def resolve_tool_loop_model(
        self,
        configured_model: str,
        has_tools: bool,
        provider_id: str = "",
        base_url: str = "",
        tool_loop_model: str = "",
        tool_loop_model_overrides: dict[str, str] | None = None,
    ) -> str:
        model = configured_model.strip() or "deepseek-chat"
        if not has_tools:
            return model

        if tool_loop_model and self._tool_loop_override_is_compatible(
            configured_model=model,
            target_model=tool_loop_model,
            provider_id=provider_id,
            base_url=base_url,
        ):
            return tool_loop_model

        configured_key = model.lower()
        map_override = (tool_loop_model_overrides or {}).get(configured_key)
        if map_override and self._tool_loop_override_is_compatible(
            configured_model=model,
            target_model=map_override,
            provider_id=provider_id,
            base_url=base_url,
        ):
            return map_override

        return model

    def build_tool_capable_model(
        self,
        *,
        profile: LLMProfile,
        runtime: RuntimeConfig,
        model_override: str | None = None,
    ) -> ToolCapableChatModel:
        return cast(
            ToolCapableChatModel,
            ChatOpenAI(
                **self.build_llm_kwargs(
                    profile=profile,
                    runtime=runtime,
                    model_override=model_override,
                )
            ),
        )

    def get_runtime_llm(
        self, runtime: RuntimeWithServices, profile: LLMProfile
    ) -> ToolCapableChatModel:
        api_key = self._profile_api_key(profile)
        signature = (
            runtime.runtime_config.llm_runtime.temperature,
            runtime.runtime_config.llm_runtime.timeout_seconds,
            profile.profile_name,
            profile.provider_id,
            profile.model,
            profile.base_url,
            api_key,
        )
        cached = runtime.llm_cache.get(signature)
        if cached is not None:
            return cached
        llm = self.build_tool_capable_model(
            profile=profile,
            runtime=runtime.runtime_config,
        )
        runtime.llm_cache[signature] = llm
        return llm

    def resolve_tool_capable_model(
        self,
        *,
        runtime: RuntimeWithServices,
        candidate: ResolvedLlmCandidate,
        has_tools: bool,
        tool_loop_model: str,
        tool_loop_model_overrides: dict[str, str],
    ) -> tuple[ToolCapableChatModel, str]:
        selected_model = self.resolve_tool_loop_model(
            str(candidate.profile.model),
            has_tools,
            candidate.profile.provider_id,
            candidate.profile.base_url,
            tool_loop_model,
            tool_loop_model_overrides,
        )
        if selected_model == str(candidate.profile.model):
            return self.get_runtime_llm(runtime, candidate.profile), selected_model
        return (
            self.build_tool_capable_model(
                profile=candidate.profile,
                runtime=runtime.runtime_config,
                model_override=selected_model,
            ),
            selected_model,
        )

    def resolve_llm_route(self, runtime: RuntimeWithServices) -> ResolvedLlmRoute:
        return resolve_agent_llm_route(
            agent_id=runtime.agent_id,
            runtime=runtime.runtime_config,
            config=self.get_app_config(),
        )

    def build_callbacks(
        self,
        *,
        run_id: str,
        session_id: str,
        trigger_type: str,
        runtime_root: Path,
        runtime_audit_store: Any,
    ) -> RuntimeCallbackBundle:
        callback = AuditCallbackHandler(
            audit_file=runtime_root / "storage" / "runs_events.jsonl",
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            audit_store=runtime_audit_store,
        )
        usage_capture = UsageCaptureCallbackHandler()
        return RuntimeCallbackBundle(
            callbacks=[
                callback,
                usage_capture,
                *build_optional_callbacks(run_id=run_id),
            ],
            usage_capture=usage_capture,
        )

    def append_llm_route_event(
        self,
        *,
        runtime: RuntimeWithServices,
        run_id: str,
        session_id: str,
        trigger_type: str,
        event: str,
        details: dict[str, Any],
    ) -> None:
        runtime.audit_store.append_step(
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            event=event,
            details=details,
        )

    @staticmethod
    def candidate_unavailable_message(
        agent_id: str,
        candidate: ResolvedLlmCandidate,
        reasons: tuple[str, ...],
    ) -> str:
        return (
            f"Agent '{agent_id}' {candidate.source} profile '{candidate.profile_name}' "
            f"is unavailable: {', '.join(reasons)}"
        )

    @staticmethod
    def route_error_message(route: ResolvedLlmRoute) -> str:
        errors = [item.strip() for item in route.errors if str(item).strip()]
        if errors:
            return "; ".join(errors)
        return f"Agent '{route.agent_id}' has no valid LLM route configured"

    def resolve_auxiliary_llm_candidate(
        self,
        runtime: RuntimeWithServices,
    ) -> ResolvedLlmCandidate | None:
        route = self.resolve_llm_route(runtime)
        if not route.valid:
            return None
        for candidate in route.candidates:
            availability = inspect_profile_availability(candidate.profile)
            if availability.available:
                return candidate
        return None

    def initial_usage_state(self, *, provider: str, model: str) -> dict[str, Any]:
        return self.usage_orchestrator.initial_usage_state(
            provider=provider,
            model=model,
        )

    @staticmethod
    def as_int(value: Any) -> int:
        return UsageOrchestrator.as_int(value)

    def accumulate_usage_from_messages(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        messages: list[Any],
        source_prefix: str,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
        fallback_provider: str | None = None,
        source_offset: int = 0,
    ) -> bool:
        return self.usage_orchestrator.accumulate_usage_from_messages(
            usage_state=usage_state,
            usage_sources=usage_sources,
            messages=messages,
            source_prefix=source_prefix,
            config=self.get_app_config(),
            fallback_model=fallback_model,
            fallback_base_url=fallback_base_url,
            fallback_provider=fallback_provider,
            source_offset=source_offset,
        )

    def usage_signature(self, usage_state: dict[str, Any]) -> str:
        return self.usage_orchestrator.usage_signature(usage_state)

    def record_usage(
        self,
        *,
        usage: dict[str, Any],
        run_id: str,
        session_id: str,
        trigger_type: str,
        agent_id: str,
        usage_store: Any,
    ) -> dict[str, Any]:
        return self.usage_orchestrator.record_usage(
            usage=usage,
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            agent_id=agent_id,
            usage_store=usage_store,
        )
