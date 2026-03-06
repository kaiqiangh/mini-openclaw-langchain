from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import (
    AppConfig,
    LLMProfile,
    RuntimeConfig,
    load_config,
    load_effective_runtime_config,
    resolve_header_templates,
    runtime_config_digest,
)
from graph.callbacks import AuditCallbackHandler, UsageCaptureCallbackHandler
from graph.agent_loop_types import StreamLoopState
from graph.memory_indexer import MemoryIndexer
from graph.prompt_builder import PromptBuilder
from graph.retrieval_orchestrator import RetrievalOrchestrator
from graph.session_manager import SessionManager
from graph.stream_orchestrator import StreamOrchestrator
from graph.tool_orchestrator import ToolOrchestrator
from graph.usage_orchestrator import UsageOrchestrator
from llm_routing import (
    ResolvedLlmCandidate,
    ResolvedLlmRoute,
    classify_llm_failure,
    inspect_profile_availability,
    resolve_agent_llm_route,
    should_fallback_for_error,
)
from observability.tracing import build_optional_callbacks
from storage.run_store import AuditStore
from storage.usage_store import UsageStore
from tools.skills_scanner import ensure_skills_snapshot
from usage.pricing import calculate_cost_breakdown, infer_provider

_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class AgentRuntime:
    agent_id: str
    root_dir: Path
    session_manager: SessionManager
    memory_indexer: MemoryIndexer
    audit_store: AuditStore
    usage_store: UsageStore
    runtime_config: RuntimeConfig
    runtime_config_digest: str
    global_config_mtime_ns: int
    agent_config_mtime_ns: int
    llm_cache: dict[tuple[float, int, str, str, str, str, str], ChatOpenAI] = field(
        default_factory=dict
    )


class AgentManager:
    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self.workspaces_dir: Path | None = None
        self.workspace_template_dir: Path | None = None
        self.config: AppConfig | None = None
        # Compatibility handles (default agent).
        self.session_manager: SessionManager | None = None
        self.memory_indexer: MemoryIndexer | None = None
        self.audit_store: AuditStore | None = None
        self.usage_store: UsageStore | None = None
        self.prompt_builder = PromptBuilder()
        self.usage_orchestrator = UsageOrchestrator()
        self.default_agent_id = "default"
        self._runtimes: dict[str, AgentRuntime] = {}
        self._app_config_mtime_ns: int = -1

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.workspaces_dir = base_dir / "workspaces"
        self.workspace_template_dir = base_dir / "workspace-template"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_template_dir.mkdir(parents=True, exist_ok=True)

        self.config = load_config(base_dir)
        self._app_config_mtime_ns = self._config_mtime_ns(base_dir / "config.json")
        self._ensure_workspace_template()
        self._ensure_workspace(self.default_agent_id)
        default_runtime = self.get_runtime(self.default_agent_id)
        self.session_manager = default_runtime.session_manager
        self.memory_indexer = default_runtime.memory_indexer
        self.audit_store = default_runtime.audit_store
        self.usage_store = default_runtime.usage_store
        self._provision_retrieval_storage_for_all_agents()

    @staticmethod
    def _profile_api_key(profile: LLMProfile) -> str:
        env_key = profile.api_key_env.strip()
        if not env_key:
            return ""
        return (os.getenv(env_key, "") or "").strip()

    @staticmethod
    def _build_llm_kwargs(
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
        api_key = AgentManager._profile_api_key(profile)
        if not api_key:
            missing_env = profile.api_key_env.strip() or "API_KEY"
            raise RuntimeError(f"{missing_env} is not configured")

        effective_timeout = max(
            5, int(runtime.llm_runtime.timeout_seconds or profile.timeout_seconds or 60)
        )
        headers = resolve_header_templates(dict(profile.default_headers))
        # Keep bearer auth by default, but preserve explicit provider auth headers.
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

    @staticmethod
    def _resolve_tool_loop_model(
        configured_model: str,
        has_tools: bool,
        provider_id: str = "",
        base_url: str = "",
        tool_loop_model: str = "",
        tool_loop_model_overrides: dict[str, str] | None = None,
    ) -> str:
        """Select a tool-compatible model when provider requirements demand it."""
        model = configured_model.strip() or "deepseek-chat"
        if not has_tools:
            return model

        if tool_loop_model and AgentManager._tool_loop_override_is_compatible(
            configured_model=model,
            target_model=tool_loop_model,
            provider_id=provider_id,
            base_url=base_url,
        ):
            return tool_loop_model

        configured_key = model.lower()
        map_override = (tool_loop_model_overrides or {}).get(configured_key)
        if map_override and AgentManager._tool_loop_override_is_compatible(
            configured_model=model,
            target_model=map_override,
            provider_id=provider_id,
            base_url=base_url,
        ):
            return map_override

        return model

    @staticmethod
    def _is_max_steps_error(exc: Exception) -> bool:
        text = str(exc).strip().lower()
        if not text:
            return False
        return (
            "recursion limit" in text
            or "max steps" in text
            or "max_steps" in text
        )

    def _require_initialized(self) -> tuple[Path, Path]:
        if self.base_dir is None or self.workspaces_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        return self.base_dir, self.workspaces_dir

    def _normalize_agent_id(self, agent_id: str | None) -> str:
        raw = (agent_id or self.default_agent_id).strip()
        if not raw:
            return self.default_agent_id
        if not _AGENT_ID_PATTERN.fullmatch(raw):
            raise ValueError("agent_id must match [A-Za-z0-9_-]{1,64}")
        return raw

    def _workspace_root(self, agent_id: str) -> Path:
        _, workspaces_dir = self._require_initialized()
        return workspaces_dir / agent_id

    def _global_config_path(self) -> Path:
        base_dir, _ = self._require_initialized()
        return base_dir / "config.json"

    @staticmethod
    def _config_mtime_ns(path: Path) -> int:
        if not path.exists():
            return -1
        return path.stat().st_mtime_ns

    def _refresh_app_config(self) -> AppConfig:
        base_dir, _ = self._require_initialized()
        config_path = self._global_config_path()
        mtime = self._config_mtime_ns(config_path)
        if self.config is None or self._app_config_mtime_ns != mtime:
            self.config = load_config(base_dir)
            self._app_config_mtime_ns = mtime
        return self.config

    def _runtime_config_paths(self, workspace_root: Path) -> tuple[Path, Path]:
        return self._global_config_path(), workspace_root / "config.json"

    def get_agent_config_path(self, agent_id: str = "default") -> Path:
        runtime = self.get_runtime(agent_id)
        return runtime.root_dir / "config.json"

    def _copy_text_if_missing(
        self, source: Path | None, target: Path, default_text: str = ""
    ) -> None:
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is not None and source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            return
        target.write_text(default_text, encoding="utf-8")

    def _copy_tree_if_missing(self, source_dir: Path, target_dir: Path) -> None:
        """Seed a workspace from template without overwriting user-managed files."""
        target_dir.mkdir(parents=True, exist_ok=True)
        if not source_dir.exists():
            return
        for item in sorted(source_dir.rglob("*")):
            rel = item.relative_to(source_dir)
            target = target_dir / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item.is_file():
                continue
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    @staticmethod
    def _is_memory_placeholder(content: str) -> bool:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return True
        if lines[0].lower() != "# memory":
            return False
        if len(lines) == 1:
            return True
        placeholder_prefixes = (
            "- keep this file concise",
            "- store stable preferences and long-lived context only",
        )
        for line in lines[1:]:
            if not any(
                line.lower().startswith(prefix) for prefix in placeholder_prefixes
            ):
                return False
        return True

    def _migrate_legacy_root_memory(self, workspace_root: Path) -> None:
        legacy_memory = workspace_root / "MEMORY.md"
        if not legacy_memory.exists() or not legacy_memory.is_file():
            return
        try:
            legacy_text = legacy_memory.read_text(encoding="utf-8")
        except Exception:
            return
        if not legacy_text.strip():
            return

        canonical_memory = workspace_root / "memory" / "MEMORY.md"
        canonical_text = ""
        if canonical_memory.exists() and canonical_memory.is_file():
            try:
                canonical_text = canonical_memory.read_text(encoding="utf-8")
            except Exception:
                return

        if canonical_text.strip() and not self._is_memory_placeholder(canonical_text):
            return

        canonical_memory.parent.mkdir(parents=True, exist_ok=True)
        canonical_memory.write_text(legacy_text, encoding="utf-8")

    def _ensure_workspace_template(self) -> None:
        base_dir, _ = self._require_initialized()
        assert self.workspace_template_dir is not None

        template = self.workspace_template_dir
        (template / "workspace").mkdir(parents=True, exist_ok=True)
        (template / "memory").mkdir(parents=True, exist_ok=True)
        (template / "knowledge").mkdir(parents=True, exist_ok=True)

        workspace_files = [
            "AGENTS.md",
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "HEARTBEAT.md",
            "BOOTSTRAP.md",
        ]
        for name in workspace_files:
            self._copy_text_if_missing(
                base_dir / "workspace" / name,
                template / "workspace" / name,
                default_text=f"# {name}\n",
            )

        self._copy_text_if_missing(
            base_dir / "memory" / "MEMORY.md",
            template / "memory" / "MEMORY.md",
            default_text="# MEMORY\n\n- Keep this file concise.\n",
        )

    def _seed_workspace_skills(self, workspace_root: Path) -> None:
        if self.base_dir is None:
            return
        source = self.base_dir / "skills"
        target = workspace_root / "skills"
        if source.exists():
            self._copy_tree_if_missing(source, target)
        else:
            target.mkdir(parents=True, exist_ok=True)

    def _ensure_workspace(self, agent_id: str) -> Path:
        if self.workspace_template_dir is None:
            raise RuntimeError("Workspace template directory is unavailable")
        root = self._workspace_root(agent_id)
        template = self.workspace_template_dir
        created_workspace = not root.exists()

        root.mkdir(parents=True, exist_ok=True)

        for rel_dir in ("workspace", "memory", "knowledge"):
            src = template / rel_dir
            dst = root / rel_dir
            if src.exists():
                self._copy_tree_if_missing(src, dst)
            else:
                dst.mkdir(parents=True, exist_ok=True)

        for rel in ("sessions/archive", "sessions/archived_sessions", "storage"):
            (root / rel).mkdir(parents=True, exist_ok=True)

        # One-time migration path for legacy single-workspace layout.
        if agent_id == self.default_agent_id and self.base_dir is not None:
            legacy_sessions = self.base_dir / "sessions"
            default_sessions = root / "sessions"
            has_default_sessions = any(default_sessions.rglob("*.json"))
            if legacy_sessions.exists() and not has_default_sessions:
                shutil.copytree(legacy_sessions, default_sessions, dirs_exist_ok=True)

            legacy_usage = self.base_dir / "storage" / "usage" / "llm_usage.jsonl"
            default_usage = root / "storage" / "usage" / "llm_usage.jsonl"
            if legacy_usage.exists() and not default_usage.exists():
                default_usage.parent.mkdir(parents=True, exist_ok=True)
                default_usage.write_text(
                    legacy_usage.read_text(encoding="utf-8"), encoding="utf-8"
                )

            legacy_knowledge = self.base_dir / "knowledge"
            default_knowledge = root / "knowledge"
            if legacy_knowledge.exists() and not any(default_knowledge.rglob("*")):
                shutil.copytree(legacy_knowledge, default_knowledge, dirs_exist_ok=True)

        self._migrate_legacy_root_memory(root)
        if created_workspace:
            self._seed_workspace_skills(root)
            ensure_skills_snapshot(root)
        if self.base_dir is not None:
            self._copy_text_if_missing(
                self.base_dir / "config.json", root / "config.json", default_text="{}\n"
            )
        return root

    def _build_runtime(self, agent_id: str) -> AgentRuntime:
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        if self.config is None:
            self.config = load_config(self.base_dir)
        workspace_root = self._ensure_workspace(agent_id)
        global_config_path, agent_config_path = self._runtime_config_paths(
            workspace_root
        )
        effective_runtime = load_effective_runtime_config(
            global_config_path, agent_config_path
        )
        effective_digest = runtime_config_digest(effective_runtime)
        runtime = AgentRuntime(
            agent_id=agent_id,
            root_dir=workspace_root,
            session_manager=SessionManager(workspace_root),
            memory_indexer=MemoryIndexer(workspace_root, config_base_dir=self.base_dir),
            audit_store=AuditStore(workspace_root),
            usage_store=UsageStore(workspace_root),
            runtime_config=effective_runtime,
            runtime_config_digest=effective_digest,
            global_config_mtime_ns=self._config_mtime_ns(global_config_path),
            agent_config_mtime_ns=self._config_mtime_ns(agent_config_path),
        )
        runtime.audit_store.ensure_schema_descriptor()
        runtime.memory_indexer.ensure_storage(
            settings=runtime.runtime_config.retrieval.memory
        )
        return runtime

    def _refresh_runtime_config(self, runtime: AgentRuntime) -> None:
        workspace_root = self._ensure_workspace(runtime.agent_id)
        runtime.root_dir = workspace_root
        global_config_path, agent_config_path = self._runtime_config_paths(
            workspace_root
        )
        global_mtime = self._config_mtime_ns(global_config_path)
        agent_mtime = self._config_mtime_ns(agent_config_path)
        if (
            runtime.global_config_mtime_ns == global_mtime
            and runtime.agent_config_mtime_ns == agent_mtime
            and runtime.runtime_config_digest
        ):
            return

        effective_runtime = load_effective_runtime_config(
            global_config_path, agent_config_path
        )
        runtime.runtime_config = effective_runtime
        runtime.runtime_config_digest = runtime_config_digest(effective_runtime)
        runtime.global_config_mtime_ns = global_mtime
        runtime.agent_config_mtime_ns = agent_mtime
        runtime.memory_indexer.ensure_storage(
            settings=runtime.runtime_config.retrieval.memory
        )

    def _provision_retrieval_storage_for_all_agents(self) -> None:
        _, workspaces_dir = self._require_initialized()
        for item in sorted(workspaces_dir.iterdir(), key=lambda p: p.name):
            if not item.is_dir():
                continue
            agent_id = item.name
            try:
                runtime = self.get_runtime(agent_id)
                runtime.memory_indexer.ensure_storage(
                    settings=runtime.runtime_config.retrieval.memory
                )
            except Exception:
                continue

    def _resolve_llm_route(self, runtime: AgentRuntime) -> ResolvedLlmRoute:
        config = self._refresh_app_config()
        return resolve_agent_llm_route(
            agent_id=runtime.agent_id,
            runtime=runtime.runtime_config,
            config=config,
        )

    def _get_runtime_llm(self, runtime: AgentRuntime, profile: LLMProfile) -> ChatOpenAI:
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
        llm = ChatOpenAI(
            **self._build_llm_kwargs(profile=profile, runtime=runtime.runtime_config)
        )
        runtime.llm_cache[signature] = llm
        return llm

    def get_runtime(self, agent_id: str = "default") -> AgentRuntime:
        self._refresh_app_config()
        normalized = self._normalize_agent_id(agent_id)
        runtime = self._runtimes.get(normalized)
        if runtime is None:
            runtime = self._build_runtime(normalized)
            self._runtimes[normalized] = runtime
            return runtime
        self._refresh_runtime_config(runtime)
        return runtime

    def get_session_manager(self, agent_id: str = "default") -> SessionManager:
        return self.get_runtime(agent_id).session_manager

    def get_memory_indexer(self, agent_id: str = "default") -> MemoryIndexer:
        return self.get_runtime(agent_id).memory_indexer

    def get_usage_store(self, agent_id: str = "default") -> UsageStore:
        return self.get_runtime(agent_id).usage_store

    def get_llm_status(self, agent_id: str = "default") -> dict[str, Any]:
        runtime = self.get_runtime(agent_id)
        return self._resolve_llm_route(runtime).to_status_dict()

    def list_agents(self) -> list[dict[str, Any]]:
        self._refresh_app_config()
        _, workspaces_dir = self._require_initialized()
        rows: list[dict[str, Any]] = []
        for item in sorted(workspaces_dir.iterdir(), key=lambda p: p.name):
            if not item.is_dir():
                continue
            sessions_dir = item / "sessions"
            active_sessions = (
                len([p for p in sessions_dir.glob("*.json") if p.is_file()])
                if sessions_dir.exists()
                else 0
            )
            archived_dir = sessions_dir / "archived_sessions"
            archived_sessions = (
                len([p for p in archived_dir.glob("*.json") if p.is_file()])
                if archived_dir.exists()
                else 0
            )
            stat = item.stat()
            llm_status = {
                "valid": False,
                "runnable": False,
                "default_profile": "",
                "fallback_profiles": [],
                "warnings": [],
                "errors": ["Failed to resolve agent LLM status"],
            }
            try:
                llm_status = self.get_llm_status(item.name)
            except Exception as exc:  # noqa: BLE001
                llm_status["errors"] = [str(exc)]
            rows.append(
                {
                    "agent_id": item.name,
                    "path": str(item),
                    "created_at": float(stat.st_ctime),
                    "updated_at": float(stat.st_mtime),
                    "active_sessions": active_sessions,
                    "archived_sessions": archived_sessions,
                    "llm_status": llm_status,
                }
            )
        return rows

    def create_agent(self, agent_id: str) -> dict[str, Any]:
        normalized = self._normalize_agent_id(agent_id)
        root = self._workspace_root(normalized)
        if root.exists():
            raise ValueError(f"Agent already exists: {normalized}")
        runtime = self.get_runtime(normalized)
        runtime.memory_indexer.rebuild_index(
            settings=runtime.runtime_config.retrieval.memory
        )
        for row in self.list_agents():
            if row.get("agent_id") == normalized:
                return row
        raise RuntimeError("Failed to create agent")

    def delete_agent(self, agent_id: str) -> bool:
        normalized = self._normalize_agent_id(agent_id)
        if normalized == self.default_agent_id:
            raise ValueError("Default agent cannot be deleted")
        root = self._workspace_root(normalized)
        if not root.exists():
            return False
        self._runtimes.pop(normalized, None)
        shutil.rmtree(root)
        return True

    def _build_callbacks(
        self,
        *,
        run_id: str,
        session_id: str,
        trigger_type: str,
        runtime_root: Path,
        runtime_audit_store: AuditStore,
    ) -> tuple[list[Any], UsageCaptureCallbackHandler]:
        callback = AuditCallbackHandler(
            audit_file=runtime_root / "storage" / "runs_events.jsonl",
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            audit_store=runtime_audit_store,
        )
        usage_capture = UsageCaptureCallbackHandler()
        # Internal audit callback is always enabled; external tracing is optional.
        return [
            callback,
            usage_capture,
            *build_optional_callbacks(run_id=run_id),
        ], usage_capture

    @staticmethod
    def _candidate_unavailable_message(
        agent_id: str,
        candidate: ResolvedLlmCandidate,
        reasons: tuple[str, ...],
    ) -> str:
        return (
            f"Agent '{agent_id}' {candidate.source} profile '{candidate.profile_name}' "
            f"is unavailable: {', '.join(reasons)}"
        )

    @staticmethod
    def _route_error_message(route: ResolvedLlmRoute) -> str:
        errors = [item.strip() for item in route.errors if str(item).strip()]
        if errors:
            return "; ".join(errors)
        return f"Agent '{route.agent_id}' has no valid LLM route configured"

    def _append_llm_route_event(
        self,
        *,
        runtime: AgentRuntime,
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

    def _resolve_auxiliary_llm_candidate(
        self,
        runtime: AgentRuntime,
    ) -> ResolvedLlmCandidate | None:
        route = self._resolve_llm_route(runtime)
        if not route.valid:
            return None
        for candidate in route.candidates:
            availability = inspect_profile_availability(candidate.profile)
            if availability.available:
                return candidate
        return None

    def _build_agent(
        self,
        *,
        llm: ChatOpenAI,
        llm_profile: LLMProfile,
        runtime: RuntimeConfig,
        system_prompt: str,
        trigger_type: str,
        run_id: str,
        session_id: str,
        runtime_root: Path,
        runtime_audit_store: AuditStore,
        llm_route: ResolvedLlmRoute,
        response_format: Any | None = None,
    ) -> tuple[Any, str]:
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        built = ToolOrchestrator.build_agent(
            config_base_dir=self.base_dir,
            runtime_root=runtime_root,
            runtime=runtime,
            llm=llm,
            llm_profile=llm_profile,
            trigger_type=trigger_type,
            run_id=run_id,
            session_id=session_id,
            runtime_audit_store=runtime_audit_store,
            system_prompt=system_prompt,
            response_format=response_format,
            resolve_tool_loop_model=lambda configured_model, has_tools, provider_id, base_url: self._resolve_tool_loop_model(
                configured_model,
                has_tools,
                provider_id,
                base_url,
                llm_route.tool_loop_model,
                llm_route.tool_loop_model_overrides,
            ),
            build_llm_kwargs=self._build_llm_kwargs,
        )
        return built.agent, built.selected_model

    @staticmethod
    def _as_text(content: Any) -> str:
        return StreamOrchestrator.as_text(content)

    @staticmethod
    def _extract_token_text(token: Any) -> list[str]:
        return StreamOrchestrator.extract_token_text(token)

    @staticmethod
    def _extract_reasoning_text(message: Any) -> list[str]:
        return StreamOrchestrator.extract_reasoning_text(message)

    @staticmethod
    def _diff_incremental(previous: str, current: str) -> str:
        return StreamOrchestrator.diff_incremental(previous, current)

    @staticmethod
    def _as_int(value: Any) -> int:
        return UsageOrchestrator.as_int(value)

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return UsageOrchestrator.as_dict(value)

    @staticmethod
    def _usage_numeric_fields() -> tuple[str, ...]:
        return UsageOrchestrator.usage_numeric_fields()

    def _merge_usage_identity(
        self, usage_state: dict[str, Any], usage_candidate: dict[str, Any]
    ) -> None:
        self.usage_orchestrator.merge_usage_identity(usage_state, usage_candidate)

    def _normalize_aggregated_usage(self, usage_state: dict[str, Any]) -> None:
        self.usage_orchestrator.normalize_aggregated_usage(usage_state)

    def _accumulate_usage_candidate(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        source_id: str,
        usage_candidate: dict[str, Any],
    ) -> bool:
        return self.usage_orchestrator.accumulate_usage_candidate(
            usage_state=usage_state,
            usage_sources=usage_sources,
            source_id=source_id,
            usage_candidate=usage_candidate,
        )

    def _accumulate_usage_from_messages(
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
            config=self.config,
            fallback_model=fallback_model,
            fallback_base_url=fallback_base_url,
            fallback_provider=fallback_provider,
            source_offset=source_offset,
        )

    def _usage_signature(self, usage_state: dict[str, Any]) -> str:
        return self.usage_orchestrator.usage_signature(usage_state)

    def _extract_usage_from_message(
        self,
        message: Any,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
        fallback_provider: str | None = None,
    ) -> dict[str, Any]:
        return self.usage_orchestrator.extract_usage_from_message(
            config=self.config,
            message=message,
            fallback_model=fallback_model,
            fallback_base_url=fallback_base_url,
            fallback_provider=fallback_provider,
        )

    def _record_usage(
        self,
        *,
        usage: dict[str, Any],
        run_id: str,
        session_id: str,
        trigger_type: str,
        agent_id: str,
        usage_store: UsageStore,
    ) -> dict[str, Any]:
        return self.usage_orchestrator.record_usage(
            usage=usage,
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            agent_id=agent_id,
            usage_store=usage_store,
        )

    def _build_messages(
        self,
        *,
        history: list[dict[str, Any]],
        message: str,
        rag_context: str | None,
    ) -> list[BaseMessage]:
        built: list[BaseMessage] = []

        for item in history:
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if not content:
                continue
            if role == "assistant":
                built.append(AIMessage(content=content))
            else:
                built.append(HumanMessage(content=content))

        if rag_context:
            built.append(SystemMessage(content=rag_context))

        built.append(HumanMessage(content=message))
        return built

    async def generate_title(self, seed_text: str, agent_id: str = "default") -> str:
        if self.config is None:
            return seed_text[:10] or "New Session"
        runtime = self.get_runtime(agent_id)
        candidate = self._resolve_auxiliary_llm_candidate(runtime)
        if candidate is None:
            return seed_text[:40] or "New Session"
        llm = self._get_runtime_llm(runtime, candidate.profile)

        prompt = (
            "Generate a short session title in plain English, at most 10 words. "
            "No quotes and no trailing punctuation. Return only the title.\n"
            f"Content: {seed_text[:200]}"
        )
        try:
            response = await llm.ainvoke(prompt)
            first_line = str(getattr(response, "content", "")).strip().splitlines()[0]
            title = " ".join(first_line.split()[:10])[:80].strip()
            return title or (seed_text[:40] or "New Session")
        except Exception:  # noqa: BLE001
            return seed_text[:40] or "New Session"

    async def summarize_messages(
        self, messages: list[dict[str, Any]], agent_id: str = "default"
    ) -> str:
        if self.config is None:
            joined = "\n".join(
                f"{m.get('role','user')}: {m.get('content','')[:80]}" for m in messages
            )
            return joined[:500]
        runtime = self.get_runtime(agent_id)
        candidate = self._resolve_auxiliary_llm_candidate(runtime)
        if candidate is None:
            corpus = "\n".join(
                f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}"
                for m in messages
            )
            return corpus[:500]
        llm = self._get_runtime_llm(runtime, candidate.profile)

        corpus = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}"
            for m in messages
        )
        prompt = (
            "Summarize the following conversation in under 500 characters. "
            "Preserve key conclusions, user preferences, and unfinished tasks.\n"
            f"{corpus[:4000]}"
        )
        try:
            response = await llm.ainvoke(prompt)
            summary = str(getattr(response, "content", "")).strip()
            return summary[:500]
        except Exception:  # noqa: BLE001
            return corpus[:500]

    def build_system_prompt(
        self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default"
    ) -> str:
        if self.config is None:
            raise RuntimeError("AgentManager is not initialized")
        runtime = self.get_runtime(agent_id)
        ensure_skills_snapshot(runtime.root_dir)
        pack = self.prompt_builder.build_system_prompt(
            base_dir=runtime.root_dir,
            runtime=runtime.runtime_config,
            rag_mode=rag_mode,
            is_first_turn=is_first_turn,
        )
        return pack.prompt

    async def run_once(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        session_id: str,
        is_first_turn: bool = False,
        output_format: str = "text",
        trigger_type: str = "chat",
        agent_id: str = "default",
    ) -> dict[str, Any]:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager must be initialized before run_once().")
        runtime_state = self.get_runtime(agent_id)
        effective_runtime = runtime_state.runtime_config
        route = self._resolve_llm_route(runtime_state)
        if not route.valid:
            raise RuntimeError(self._route_error_message(route))

        retrieval_envelope = RetrievalOrchestrator.build_envelope(
            runtime=effective_runtime,
            memory_indexer=runtime_state.memory_indexer,
            message=message,
        )

        messages = self._build_messages(
            history=history, message=message, rag_context=retrieval_envelope.rag_context
        )
        system_prompt = self.build_system_prompt(
            rag_mode=effective_runtime.rag_mode,
            is_first_turn=is_first_turn,
            agent_id=agent_id,
        )

        response_schema = None
        if output_format == "json":
            from pydantic import BaseModel

            class RunJsonResponse(BaseModel):
                answer: str

            response_schema = RunJsonResponse

        last_error: Exception | None = None
        for candidate_index, candidate in enumerate(route.candidates):
            availability = inspect_profile_availability(candidate.profile)
            if not availability.available:
                unavailable_message = self._candidate_unavailable_message(
                    runtime_state.agent_id,
                    candidate,
                    availability.reasons,
                )
                skipped_run_id = str(uuid.uuid4())
                self._append_llm_route_event(
                    runtime=runtime_state,
                    run_id=skipped_run_id,
                    session_id=session_id,
                    trigger_type=trigger_type,
                    event="llm_route_skipped",
                    details={
                        "profile": candidate.profile_name,
                        "source": candidate.source,
                        "reasons": list(availability.reasons),
                    },
                )
                if candidate.source == "default":
                    raise RuntimeError(unavailable_message)
                continue

            llm = self._get_runtime_llm(runtime_state, candidate.profile)
            for attempt in range(effective_runtime.agent_runtime.max_retries + 1):
                run_id = str(uuid.uuid4())
                self._append_llm_route_event(
                    runtime=runtime_state,
                    run_id=run_id,
                    session_id=session_id,
                    trigger_type=trigger_type,
                    event="llm_route_resolved",
                    details={
                        "profile": candidate.profile_name,
                        "source": candidate.source,
                        "candidate_index": candidate_index,
                        "attempt": attempt + 1,
                    },
                )
                if candidate.source == "fallback":
                    self._append_llm_route_event(
                        runtime=runtime_state,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        event="llm_fallback_selected",
                        details={
                            "profile": candidate.profile_name,
                            "candidate_index": candidate_index,
                            "attempt": attempt + 1,
                        },
                    )
                try:
                    agent, active_model = self._build_agent(
                        llm=llm,
                        llm_profile=candidate.profile,
                        runtime=effective_runtime,
                        system_prompt=system_prompt,
                        trigger_type=trigger_type,
                        run_id=run_id,
                        session_id=session_id,
                        runtime_root=runtime_state.root_dir,
                        runtime_audit_store=runtime_state.audit_store,
                        llm_route=route,
                        response_format=response_schema,
                    )

                    callbacks, usage_capture = self._build_callbacks(
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        runtime_root=runtime_state.root_dir,
                        runtime_audit_store=runtime_state.audit_store,
                    )
                    config = {
                        "recursion_limit": effective_runtime.agent_runtime.max_steps,
                        "callbacks": callbacks,
                        "configurable": {"thread_id": session_id},
                    }

                    result = await agent.ainvoke({"messages": messages}, config=config)
                    usage_payload: dict[str, Any] | None = None
                    default_provider = infer_provider(
                        active_model,
                        base_url=candidate.profile.base_url,
                        explicit_provider=candidate.profile.provider_id,
                    )
                    usage_state: dict[str, Any] = (
                        self.usage_orchestrator.initial_usage_state(
                            provider=default_provider,
                            model=active_model,
                        )
                    )
                    usage_sources: dict[str, dict[str, int]] = {}

                    captured_messages = usage_capture.snapshot()
                    self._accumulate_usage_from_messages(
                        usage_state=usage_state,
                        usage_sources=usage_sources,
                        messages=captured_messages,
                        source_prefix=f"llm_end:{run_id}",
                        fallback_model=active_model,
                        fallback_base_url=candidate.profile.base_url,
                        fallback_provider=candidate.profile.provider_id,
                    )

                    output_messages = result.get("messages", [])
                    if (
                        isinstance(output_messages, list)
                        and self._as_int(usage_state.get("total_tokens", 0)) <= 0
                    ):
                        # Fallback for providers/environments where callback payloads are sparse.
                        self._accumulate_usage_from_messages(
                            usage_state=usage_state,
                            usage_sources=usage_sources,
                            messages=output_messages,
                            source_prefix=f"result:{run_id}",
                            fallback_model=active_model,
                            fallback_base_url=candidate.profile.base_url,
                            fallback_provider=candidate.profile.provider_id,
                        )

                    if self._as_int(usage_state.get("total_tokens", 0)) > 0:
                        usage_payload = self._record_usage(
                            usage=usage_state,
                            run_id=run_id,
                            session_id=session_id,
                            trigger_type=trigger_type,
                            agent_id=agent_id,
                            usage_store=runtime_state.usage_store,
                        )

                    if output_format == "json":
                        return {
                            "structured_response": result.get("structured_response"),
                            "messages": result.get("messages", []),
                            "usage": usage_payload or {},
                        }
                    text = ""
                    if output_messages:
                        text = self._as_text(
                            getattr(output_messages[-1], "content", "")
                        )
                    return {
                        "text": text,
                        "messages": output_messages,
                        "usage": usage_payload or {},
                    }
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < effective_runtime.agent_runtime.max_retries:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue

                    failure_kind = classify_llm_failure(exc)
                    has_more_candidates = candidate_index + 1 < len(route.candidates)
                    if has_more_candidates and should_fallback_for_error(
                        route.fallback_policy, failure_kind
                    ):
                        next_candidate = route.candidates[candidate_index + 1]
                        self._append_llm_route_event(
                            runtime=runtime_state,
                            run_id=run_id,
                            session_id=session_id,
                            trigger_type=trigger_type,
                            event="llm_fallback_attempt",
                            details={
                                "from_profile": candidate.profile_name,
                                "to_profile": next_candidate.profile_name,
                                "failure_kind": failure_kind,
                                "error": str(exc),
                            },
                        )
                        break

                    self._append_llm_route_event(
                        runtime=runtime_state,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        event="llm_route_exhausted",
                        details={
                            "profile": candidate.profile_name,
                            "failure_kind": failure_kind,
                            "error": str(exc),
                        },
                    )
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Agent '{agent_id}' has no available LLM candidates")

    async def astream(
        self,
        message: str,
        history: list[dict[str, Any]],
        session_id: str,
        is_first_turn: bool = False,
        trigger_type: str = "chat",
        agent_id: str = "default",
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not self.base_dir or not self.config:
            raise RuntimeError("AgentManager must be initialized before astream().")
        runtime_state = self.get_runtime(agent_id)
        effective_runtime = runtime_state.runtime_config
        route = self._resolve_llm_route(runtime_state)
        if not route.valid:
            yield {
                "type": "error",
                "data": {
                    "error": self._route_error_message(route),
                    "code": "stream_failed",
                    "run_id": str(uuid.uuid4()),
                    "attempt": 0,
                },
            }
            return

        retrieval_envelope = RetrievalOrchestrator.build_envelope(
            runtime=effective_runtime,
            memory_indexer=runtime_state.memory_indexer,
            message=message,
        )
        rag_mode = retrieval_envelope.rag_mode
        results = retrieval_envelope.results
        if rag_mode:
            yield {"type": "retrieval", "data": {"query": message, "results": results}}

        system_prompt = self.build_system_prompt(
            rag_mode=rag_mode, is_first_turn=is_first_turn, agent_id=agent_id
        )
        messages = self._build_messages(
            history=history,
            message=message,
            rag_context=retrieval_envelope.rag_context,
        )

        stream_state = StreamLoopState()
        seed_candidate = route.candidates[0]
        default_provider = infer_provider(
            seed_candidate.profile.model,
            base_url=seed_candidate.profile.base_url,
            explicit_provider=seed_candidate.profile.provider_id,
        )
        usage_state: dict[str, Any] = self.usage_orchestrator.initial_usage_state(
            provider=default_provider,
            model=seed_candidate.profile.model,
        )
        usage_sources: dict[str, dict[str, int]] = {}
        usage_signature = ""
        attempt_number = 0

        for candidate_index, candidate in enumerate(route.candidates):
            availability = inspect_profile_availability(candidate.profile)
            if not availability.available:
                skipped_run_id = str(uuid.uuid4())
                self._append_llm_route_event(
                    runtime=runtime_state,
                    run_id=skipped_run_id,
                    session_id=session_id,
                    trigger_type=trigger_type,
                    event="llm_route_skipped",
                    details={
                        "profile": candidate.profile_name,
                        "source": candidate.source,
                        "reasons": list(availability.reasons),
                    },
                )
                if candidate.source == "default":
                    yield {
                        "type": "error",
                        "data": {
                            "error": self._candidate_unavailable_message(
                                runtime_state.agent_id,
                                candidate,
                                availability.reasons,
                            ),
                            "code": "stream_failed",
                            "run_id": skipped_run_id,
                            "attempt": attempt_number,
                        },
                    }
                    return
                continue

            llm = self._get_runtime_llm(runtime_state, candidate.profile)
            for retry_index in range(effective_runtime.agent_runtime.max_retries + 1):
                attempt_number += 1
                run_id = str(uuid.uuid4())
                try:
                    self._append_llm_route_event(
                        runtime=runtime_state,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        event="llm_route_resolved",
                        details={
                            "profile": candidate.profile_name,
                            "source": candidate.source,
                            "candidate_index": candidate_index,
                            "attempt": attempt_number,
                        },
                    )
                    if candidate.source == "fallback":
                        self._append_llm_route_event(
                            runtime=runtime_state,
                            run_id=run_id,
                            session_id=session_id,
                            trigger_type=trigger_type,
                            event="llm_fallback_selected",
                            details={
                                "profile": candidate.profile_name,
                                "candidate_index": candidate_index,
                                "attempt": attempt_number,
                            },
                        )

                    yield {
                        "type": "run_start",
                        "data": {"run_id": run_id, "attempt": attempt_number},
                    }
                    agent, active_model = self._build_agent(
                        llm=llm,
                        llm_profile=candidate.profile,
                        runtime=effective_runtime,
                        system_prompt=system_prompt,
                        trigger_type=trigger_type,
                        run_id=run_id,
                        session_id=session_id,
                        runtime_root=runtime_state.root_dir,
                        runtime_audit_store=runtime_state.audit_store,
                        llm_route=route,
                    )

                    callbacks, usage_capture = self._build_callbacks(
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        runtime_root=runtime_state.root_dir,
                        runtime_audit_store=runtime_state.audit_store,
                    )
                    usage_capture_offset = 0
                    usage_state["provider"] = infer_provider(
                        active_model,
                        base_url=candidate.profile.base_url,
                        explicit_provider=candidate.profile.provider_id,
                    )
                    usage_state["model"] = active_model

                    config = {
                        "recursion_limit": effective_runtime.agent_runtime.max_steps,
                        "callbacks": callbacks,
                        "configurable": {"thread_id": session_id},
                    }

                    async for mode, chunk in agent.astream(
                        {"messages": messages},
                        stream_mode=["updates", "messages"],
                        config=config,
                    ):
                        if mode == "updates" and isinstance(chunk, dict):
                            for node, payload in chunk.items():
                                if not isinstance(payload, dict):
                                    continue
                                msgs = payload.get("messages", [])
                                if not isinstance(msgs, list) or not msgs:
                                    continue
                                latest = msgs[-1]
                                yield {
                                    "type": "agent_update",
                                    "data": {
                                        "run_id": run_id,
                                        "node": node,
                                        "message_count": len(msgs),
                                        "preview": self._as_text(
                                            getattr(latest, "content", "")
                                        )[:500],
                                    },
                                }
                                stream_state.emitted_agent_update = True

                                if node == "model":
                                    tool_calls = getattr(latest, "tool_calls", None)
                                    if isinstance(tool_calls, list) and tool_calls:
                                        for call in tool_calls:
                                            yield {
                                                "type": "tool_start",
                                                "data": {
                                                    "run_id": run_id,
                                                    "tool": str(
                                                        call.get("name", "unknown")
                                                    ),
                                                    "input": call.get("args", {}),
                                                },
                                            }
                                    else:
                                        content = self._as_text(
                                            getattr(latest, "content", "")
                                        )
                                        if content:
                                            stream_state.fallback_final_text = content
                                            if stream_state.token_source is None:
                                                delta = self._diff_incremental(
                                                    stream_state.latest_model_snapshot,
                                                    content,
                                                )
                                                stream_state.latest_model_snapshot = (
                                                    content
                                                )
                                                if delta:
                                                    if (
                                                        stream_state.pending_new_response
                                                    ):
                                                        yield {
                                                            "type": "new_response",
                                                            "data": {},
                                                        }
                                                        stream_state.pending_new_response = (
                                                            False
                                                        )
                                                    stream_state.token_source = "updates"
                                                    stream_state.final_tokens.append(
                                                        delta
                                                    )
                                                    yield {
                                                        "type": "token",
                                                        "data": {
                                                            "content": delta,
                                                            "source": "updates",
                                                        },
                                                    }

                                        for reasoning in self._extract_reasoning_text(
                                            latest
                                        ):
                                            normalized = reasoning.strip()
                                            if (
                                                not normalized
                                                or normalized
                                                in stream_state.emitted_reasoning
                                            ):
                                                continue
                                            stream_state.emitted_reasoning.add(
                                                normalized
                                            )
                                            yield {
                                                "type": "reasoning",
                                                "data": {
                                                    "run_id": run_id,
                                                    "content": normalized[:1000],
                                                },
                                            }

                                if node == "tools":
                                    for tool_msg in msgs:
                                        yield {
                                            "type": "tool_end",
                                            "data": {
                                                "run_id": run_id,
                                                "tool": str(
                                                    getattr(tool_msg, "name", None)
                                                    or getattr(
                                                        tool_msg,
                                                        "tool_call_id",
                                                        "tool",
                                                    )
                                                ),
                                                "output": self._as_text(
                                                    getattr(tool_msg, "content", "")
                                                ),
                                            },
                                        }
                                        stream_state.pending_new_response = True

                        if (
                            mode == "messages"
                            and isinstance(chunk, tuple)
                            and len(chunk) == 2
                        ):
                            token, metadata = chunk
                            node = (
                                metadata.get("langgraph_node", "")
                                if isinstance(metadata, dict)
                                else ""
                            )
                            if node != "model":
                                continue

                            if stream_state.token_source not in {None, "messages"}:
                                continue

                            if not stream_state.emitted_agent_update:
                                yield {
                                    "type": "agent_update",
                                    "data": {
                                        "run_id": run_id,
                                        "node": "model",
                                        "message_count": 1,
                                        "preview": "Streaming token output",
                                    },
                                }
                                stream_state.emitted_agent_update = True

                            for text in self._extract_token_text(token):
                                if not text:
                                    continue
                                stream_state.token_source = "messages"
                                if stream_state.pending_new_response:
                                    yield {"type": "new_response", "data": {}}
                                    stream_state.pending_new_response = False
                                stream_state.final_tokens.append(text)
                                yield {
                                    "type": "token",
                                    "data": {
                                        "content": text,
                                        "source": "messages",
                                    },
                                }

                        captured_messages = usage_capture.snapshot()
                        if usage_capture_offset < len(captured_messages):
                            usage_changed = self._accumulate_usage_from_messages(
                                usage_state=usage_state,
                                usage_sources=usage_sources,
                                messages=captured_messages[usage_capture_offset:],
                                source_prefix=f"llm_end:{run_id}",
                                fallback_model=active_model,
                                fallback_base_url=candidate.profile.base_url,
                                fallback_provider=candidate.profile.provider_id,
                                source_offset=usage_capture_offset,
                            )
                            usage_capture_offset = len(captured_messages)
                            if usage_changed:
                                signature = self._usage_signature(usage_state)
                                if signature != usage_signature:
                                    usage_signature = signature
                                    cost = calculate_cost_breakdown(
                                        provider=str(
                                            usage_state.get("provider", "unknown")
                                        ),
                                        model=str(usage_state.get("model", "unknown")),
                                        input_tokens=self._as_int(
                                            usage_state.get("input_tokens", 0)
                                        ),
                                        input_uncached_tokens=self._as_int(
                                            usage_state.get(
                                                "input_uncached_tokens", 0
                                            )
                                        ),
                                        input_cache_read_tokens=self._as_int(
                                            usage_state.get(
                                                "input_cache_read_tokens", 0
                                            )
                                        ),
                                        input_cache_write_tokens_5m=self._as_int(
                                            usage_state.get(
                                                "input_cache_write_tokens_5m", 0
                                            )
                                        ),
                                        input_cache_write_tokens_1h=self._as_int(
                                            usage_state.get(
                                                "input_cache_write_tokens_1h", 0
                                            )
                                        ),
                                        input_cache_write_tokens_unknown=self._as_int(
                                            usage_state.get(
                                                "input_cache_write_tokens_unknown",
                                                0,
                                            )
                                        ),
                                        output_tokens=self._as_int(
                                            usage_state.get("output_tokens", 0)
                                        ),
                                    )
                                    yield {
                                        "type": "usage",
                                        "data": {
                                            "run_id": run_id,
                                            "agent_id": agent_id,
                                            "provider": usage_state.get(
                                                "provider", "unknown"
                                            ),
                                            "model": usage_state.get(
                                                "model", "unknown"
                                            ),
                                            **usage_state,
                                            "pricing": cost,
                                            "priced": bool(
                                                cost.get("priced", False)
                                            ),
                                            "cost_usd": cost.get("total_cost_usd"),
                                        },
                                    }

                    captured_messages = usage_capture.snapshot()
                    if usage_capture_offset < len(captured_messages):
                        self._accumulate_usage_from_messages(
                            usage_state=usage_state,
                            usage_sources=usage_sources,
                            messages=captured_messages[usage_capture_offset:],
                            source_prefix=f"llm_end:{run_id}",
                            fallback_model=active_model,
                            fallback_base_url=candidate.profile.base_url,
                            fallback_provider=candidate.profile.provider_id,
                            source_offset=usage_capture_offset,
                        )

                    final_content = (
                        "".join(stream_state.final_tokens).strip()
                        or stream_state.fallback_final_text
                    )
                    enriched_usage = {}
                    if self._as_int(usage_state.get("total_tokens", 0)) > 0:
                        enriched_usage = self._record_usage(
                            usage=usage_state,
                            run_id=run_id,
                            session_id=session_id,
                            trigger_type=trigger_type,
                            agent_id=agent_id,
                            usage_store=runtime_state.usage_store,
                        )
                    yield {
                        "type": "done",
                        "data": {
                            "content": final_content,
                            "session_id": session_id,
                            "agent_id": agent_id,
                            "run_id": run_id,
                            "token_source": stream_state.token_source or "fallback",
                            "usage": enriched_usage,
                        },
                    }
                    return

                except Exception as exc:  # noqa: BLE001
                    if retry_index < effective_runtime.agent_runtime.max_retries:
                        await asyncio.sleep(0.5 * (2**retry_index))
                        continue

                    failure_kind = classify_llm_failure(exc)
                    has_more_candidates = candidate_index + 1 < len(route.candidates)
                    if has_more_candidates and should_fallback_for_error(
                        route.fallback_policy, failure_kind
                    ):
                        next_candidate = route.candidates[candidate_index + 1]
                        self._append_llm_route_event(
                            runtime=runtime_state,
                            run_id=run_id,
                            session_id=session_id,
                            trigger_type=trigger_type,
                            event="llm_fallback_attempt",
                            details={
                                "from_profile": candidate.profile_name,
                                "to_profile": next_candidate.profile_name,
                                "failure_kind": failure_kind,
                                "error": str(exc),
                            },
                        )
                        stream_state.pending_new_response = True
                        break

                    self._append_llm_route_event(
                        runtime=runtime_state,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        event="llm_route_exhausted",
                        details={
                            "profile": candidate.profile_name,
                            "failure_kind": failure_kind,
                            "error": str(exc),
                        },
                    )
                    error_code = (
                        "max_steps_reached"
                        if self._is_max_steps_error(exc)
                        else "stream_failed"
                    )
                    yield {
                        "type": "error",
                        "data": {
                            "error": str(exc),
                            "code": error_code,
                            "run_id": run_id,
                            "attempt": attempt_number,
                        },
                    }
                    return

        yield {
            "type": "error",
            "data": {
                "error": f"Agent '{agent_id}' has no available LLM candidates",
                "code": "stream_failed",
                "run_id": str(uuid.uuid4()),
                "attempt": attempt_number,
            },
        }
