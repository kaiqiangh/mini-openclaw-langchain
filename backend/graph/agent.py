from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import (
    AppConfig,
    RuntimeConfig,
    load_config,
    load_effective_runtime_config,
    runtime_config_digest,
)
from graph.callbacks import AuditCallbackHandler, UsageCaptureCallbackHandler
from graph.memory_indexer import MemoryIndexer
from graph.prompt_builder import PromptBuilder
from graph.session_manager import SessionManager
from observability.tracing import build_optional_callbacks
from storage.run_store import AuditStore
from storage.usage_store import UsageStore
from tools import get_all_tools, get_explicit_enabled_tools, get_tool_runner
from tools.base import ToolContext
from tools.langchain_tools import build_langchain_tools
from usage.normalization import extract_usage_from_message
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
    llm: ChatOpenAI | None = None
    llm_signature: tuple[float, int] | None = None


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
        self.default_agent_id = "default"
        self._runtimes: dict[str, AgentRuntime] = {}

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.workspaces_dir = base_dir / "workspaces"
        self.workspace_template_dir = base_dir / "workspace-template"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_template_dir.mkdir(parents=True, exist_ok=True)

        self.config = load_config(base_dir)
        self._ensure_workspace_template()
        self._ensure_workspace(self.default_agent_id)
        default_runtime = self.get_runtime(self.default_agent_id)
        self.session_manager = default_runtime.session_manager
        self.memory_indexer = default_runtime.memory_indexer
        self.audit_store = default_runtime.audit_store
        self.usage_store = default_runtime.usage_store
        self._provision_retrieval_storage_for_all_agents()

    @staticmethod
    def _build_llm(config: AppConfig, runtime: RuntimeConfig) -> ChatOpenAI:
        llm_kwargs: dict[str, Any] = {
            "model": config.secrets.deepseek_model,
            "api_key": SecretStr(config.secrets.deepseek_api_key),
            "base_url": config.secrets.deepseek_base_url,
            "temperature": runtime.llm_runtime.temperature,
            "timeout": runtime.llm_runtime.timeout_seconds,
        }
        return ChatOpenAI(**llm_kwargs)

    @staticmethod
    def _resolve_tool_loop_model(configured_model: str, has_tools: bool) -> str:
        """Select a tool-compatible model when provider requirements demand it."""
        model = configured_model.strip() or "deepseek-chat"
        if not has_tools:
            return model
        if model.lower() != "deepseek-reasoner":
            return model
        override = (os.getenv("DEEPSEEK_TOOL_MODEL", "deepseek-chat") or "").strip()
        return override or model

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

    def _sync_skills_snapshot(self, workspace_root: Path) -> None:
        if self.base_dir is None:
            return
        source = self.base_dir / "SKILLS_SNAPSHOT.md"
        target = workspace_root / "SKILLS_SNAPSHOT.md"
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        elif not target.exists():
            target.write_text(
                "<available_skills>\n</available_skills>\n", encoding="utf-8"
            )

    def _sync_skills_directory(self, workspace_root: Path) -> None:
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
        self._sync_skills_directory(root)
        self._sync_skills_snapshot(root)
        if self.base_dir is not None:
            self._copy_text_if_missing(
                self.base_dir / "config.json", root / "config.json", default_text="{}\n"
            )
        return root

    def _build_runtime(self, agent_id: str) -> AgentRuntime:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager is not initialized")
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

    def _get_runtime_llm(self, runtime: AgentRuntime) -> ChatOpenAI:
        if self.config is None:
            raise RuntimeError("AgentManager is not initialized")
        signature = (
            runtime.runtime_config.llm_runtime.temperature,
            runtime.runtime_config.llm_runtime.timeout_seconds,
        )
        if runtime.llm is not None and runtime.llm_signature == signature:
            return runtime.llm
        runtime.llm = self._build_llm(self.config, runtime.runtime_config)
        runtime.llm_signature = signature
        return runtime.llm

    def get_runtime(self, agent_id: str = "default") -> AgentRuntime:
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

    def list_agents(self) -> list[dict[str, Any]]:
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
            rows.append(
                {
                    "agent_id": item.name,
                    "path": str(item),
                    "created_at": float(stat.st_ctime),
                    "updated_at": float(stat.st_mtime),
                    "active_sessions": active_sessions,
                    "archived_sessions": archived_sessions,
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

    def _build_agent(
        self,
        *,
        llm: ChatOpenAI,
        runtime: RuntimeConfig,
        system_prompt: str,
        trigger_type: str,
        run_id: str,
        session_id: str,
        runtime_root: Path,
        runtime_audit_store: AuditStore,
        response_format: Any | None = None,
    ) -> tuple[Any, str]:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager is not initialized")
        config = self.config

        mini_tools = get_all_tools(
            runtime_root,
            runtime,
            trigger_type,
            config_base_dir=self.base_dir,
        )
        explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
        runner = get_tool_runner(
            runtime_root,
            runtime_audit_store,
            repeat_identical_failure_limit=runtime.tool_retry_guard.repeat_identical_failure_limit,
        )
        langchain_tools = build_langchain_tools(
            tools=mini_tools,
            runner=runner,
            context=ToolContext(
                workspace_root=runtime_root,
                trigger_type=trigger_type,
                explicit_enabled_tools=tuple(explicit_enabled_tools),
                run_id=run_id,
                session_id=session_id,
            ),
        )
        configured_model = str(config.secrets.deepseek_model)
        selected_model = self._resolve_tool_loop_model(
            configured_model=configured_model,
            has_tools=bool(langchain_tools),
        )
        active_llm = llm
        if selected_model != configured_model:
            active_llm = ChatOpenAI(
                model=selected_model,
                api_key=SecretStr(config.secrets.deepseek_api_key),
                base_url=config.secrets.deepseek_base_url,
                temperature=runtime.llm_runtime.temperature,
                timeout=runtime.llm_runtime.timeout_seconds,
            )

        if response_format is None:
            return create_agent(
                model=active_llm,
                tools=langchain_tools,
                system_prompt=system_prompt,
            ), selected_model

        return create_agent(
            model=active_llm,
            tools=langchain_tools,
            system_prompt=system_prompt,
            response_format=response_format,
        ), selected_model

    @staticmethod
    def _as_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)

    @staticmethod
    def _extract_token_text(token: Any) -> list[str]:
        texts: list[str] = []

        blocks = getattr(token, "content_blocks", None)
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type", ""))
                if btype in {"text", "text_chunk"}:
                    text = block.get("text") or block.get("content") or ""
                    if text:
                        texts.append(str(text))

        if not texts:
            content = getattr(token, "content", None)
            if isinstance(content, str) and content:
                texts.append(content)

        return texts

    @staticmethod
    def _extract_reasoning_text(message: Any) -> list[str]:
        texts: list[str] = []
        blocks = getattr(message, "content_blocks", None)
        if not isinstance(blocks, list):
            return texts

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type", "")).lower()
            if btype not in {
                "reasoning",
                "reasoning_chunk",
                "thinking",
                "thinking_chunk",
            }:
                continue
            text = (
                block.get("text")
                or block.get("content")
                or block.get("reasoning")
                or ""
            )
            if text:
                texts.append(str(text))
        return texts

    @staticmethod
    def _diff_incremental(previous: str, current: str) -> str:
        if not current:
            return ""
        if not previous:
            return current
        if current.startswith(previous):
            return current[len(previous) :]
        if current == previous:
            return ""
        return current

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _usage_numeric_fields() -> tuple[str, ...]:
        return (
            "input_tokens",
            "input_uncached_tokens",
            "input_cache_read_tokens",
            "input_cache_write_tokens_5m",
            "input_cache_write_tokens_1h",
            "input_cache_write_tokens_unknown",
            "output_tokens",
            "reasoning_tokens",
            "tool_input_tokens",
            "total_tokens",
        )

    def _merge_usage_identity(
        self, usage_state: dict[str, Any], usage_candidate: dict[str, Any]
    ) -> None:
        for field in ("provider", "model", "model_source", "usage_source"):
            value = str(usage_candidate.get(field, "")).strip()
            if not value:
                continue
            current = str(usage_state.get(field, "")).strip()
            if value.lower() == "unknown" and current and current.lower() != "unknown":
                continue
            if (
                current
                and current.lower() != "unknown"
                and value.lower() != "unknown"
                and current != value
            ):
                if field in {"provider", "model"}:
                    usage_state[field] = "mixed"
                    continue
                # Keep existing source label when both are non-empty and disagree.
                continue
            usage_state[field] = value

    def _normalize_aggregated_usage(self, usage_state: dict[str, Any]) -> None:
        input_tokens = self._as_int(usage_state.get("input_tokens", 0))
        input_uncached_tokens = self._as_int(
            usage_state.get("input_uncached_tokens", 0)
        )
        cache_read_tokens = self._as_int(
            usage_state.get("input_cache_read_tokens", 0)
        )
        cache_write_5m_tokens = self._as_int(
            usage_state.get("input_cache_write_tokens_5m", 0)
        )
        cache_write_1h_tokens = self._as_int(
            usage_state.get("input_cache_write_tokens_1h", 0)
        )
        cache_write_unknown_tokens = self._as_int(
            usage_state.get("input_cache_write_tokens_unknown", 0)
        )
        output_tokens = self._as_int(usage_state.get("output_tokens", 0))
        reasoning_tokens = self._as_int(usage_state.get("reasoning_tokens", 0))
        tool_input_tokens = self._as_int(usage_state.get("tool_input_tokens", 0))
        total_tokens = self._as_int(usage_state.get("total_tokens", 0))

        cache_write_total = (
            cache_write_5m_tokens + cache_write_1h_tokens + cache_write_unknown_tokens
        )

        if input_tokens <= 0 and (
            input_uncached_tokens > 0 or cache_read_tokens > 0 or cache_write_total > 0
        ):
            input_tokens = input_uncached_tokens + cache_read_tokens + cache_write_total

        if input_uncached_tokens <= 0 and input_tokens > 0:
            input_uncached_tokens = max(
                0, input_tokens - cache_read_tokens - cache_write_total
            )

        if input_uncached_tokens > input_tokens:
            input_uncached_tokens = input_tokens

        computed_total = (
            input_tokens + output_tokens + tool_input_tokens + reasoning_tokens
        )
        if total_tokens <= 0:
            total_tokens = computed_total
        else:
            total_tokens = max(total_tokens, computed_total)

        usage_state["input_tokens"] = input_tokens
        usage_state["input_uncached_tokens"] = input_uncached_tokens
        usage_state["input_cache_read_tokens"] = cache_read_tokens
        usage_state["input_cache_write_tokens_5m"] = cache_write_5m_tokens
        usage_state["input_cache_write_tokens_1h"] = cache_write_1h_tokens
        usage_state["input_cache_write_tokens_unknown"] = cache_write_unknown_tokens
        usage_state["output_tokens"] = output_tokens
        usage_state["reasoning_tokens"] = reasoning_tokens
        usage_state["tool_input_tokens"] = tool_input_tokens
        usage_state["total_tokens"] = total_tokens

    def _accumulate_usage_candidate(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        source_id: str,
        usage_candidate: dict[str, Any],
    ) -> bool:
        source_key = source_id.strip()
        if not source_key:
            return False

        has_signal = False
        for field in self._usage_numeric_fields():
            if self._as_int(usage_candidate.get(field, 0)) > 0:
                has_signal = True
                break
        if not has_signal:
            return False

        previous = usage_sources.get(
            source_key, {field: 0 for field in self._usage_numeric_fields()}
        )

        changed = False
        for field in self._usage_numeric_fields():
            prior_value = self._as_int(previous.get(field, 0))
            incoming_value = self._as_int(usage_candidate.get(field, 0))
            next_value = max(prior_value, incoming_value)
            if next_value <= prior_value:
                continue
            delta = next_value - prior_value
            usage_state[field] = self._as_int(usage_state.get(field, 0)) + delta
            previous[field] = next_value
            changed = True

        if changed:
            usage_sources[source_key] = previous
            self._normalize_aggregated_usage(usage_state)
        self._merge_usage_identity(usage_state, usage_candidate)
        return changed

    def _accumulate_usage_from_messages(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        messages: list[Any],
        source_prefix: str,
        fallback_model: str | None = None,
        source_offset: int = 0,
    ) -> bool:
        changed = False
        for index, message in enumerate(messages):
            candidate = self._extract_usage_from_message(
                message, fallback_model=fallback_model
            )
            source_id = str(getattr(message, "id", "")).strip()
            if source_id:
                source_key = f"{source_prefix}:{source_id}"
            else:
                source_key = f"{source_prefix}:{source_offset + index}"
            changed = (
                self._accumulate_usage_candidate(
                    usage_state=usage_state,
                    usage_sources=usage_sources,
                    source_id=source_key,
                    usage_candidate=candidate,
                )
                or changed
            )
        return changed

    def _usage_signature(self, usage_state: dict[str, Any]) -> str:
        parts = [str(usage_state.get(field, "")) for field in self._usage_numeric_fields()]
        parts.extend(
            [
                str(usage_state.get("provider", "")),
                str(usage_state.get("model", "")),
                str(usage_state.get("model_source", "")),
                str(usage_state.get("usage_source", "")),
            ]
        )
        return "|".join(parts)

    def _extract_usage_from_message(
        self, message: Any, fallback_model: str | None = None
    ) -> dict[str, Any]:
        if self.config is None:
            return {}
        model_fallback = (fallback_model or self.config.secrets.deepseek_model).strip()
        if not model_fallback:
            model_fallback = self.config.secrets.deepseek_model
        return extract_usage_from_message(
            message=message,
            fallback_model=model_fallback,
            fallback_base_url=self.config.secrets.deepseek_base_url,
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
        provider = str(usage.get("provider", "unknown")).strip() or "unknown"
        model = str(usage.get("model", "unknown")).strip() or "unknown"
        usage_cost = calculate_cost_breakdown(
            provider=provider,
            model=model,
            input_tokens=self._as_int(usage.get("input_tokens", 0)),
            input_uncached_tokens=self._as_int(
                usage.get("input_uncached_tokens", 0)
            ),
            input_cache_read_tokens=self._as_int(
                usage.get("input_cache_read_tokens", 0)
            ),
            input_cache_write_tokens_5m=self._as_int(
                usage.get("input_cache_write_tokens_5m", 0)
            ),
            input_cache_write_tokens_1h=self._as_int(
                usage.get("input_cache_write_tokens_1h", 0)
            ),
            input_cache_write_tokens_unknown=self._as_int(
                usage.get("input_cache_write_tokens_unknown", 0)
            ),
            output_tokens=self._as_int(usage.get("output_tokens", 0)),
        )
        enriched = {
            "schema_version": 2,
            "agent_id": agent_id,
            "provider": provider,
            "model": model,
            "trigger_type": trigger_type,
            "run_id": run_id,
            "session_id": session_id,
            "model_source": str(usage.get("model_source", "unknown")),
            "usage_source": str(usage.get("usage_source", "unknown")),
            "input_tokens": self._as_int(usage.get("input_tokens", 0)),
            "input_uncached_tokens": self._as_int(
                usage.get("input_uncached_tokens", 0)
            ),
            "input_cache_read_tokens": self._as_int(
                usage.get("input_cache_read_tokens", 0)
            ),
            "input_cache_write_tokens_5m": self._as_int(
                usage.get("input_cache_write_tokens_5m", 0)
            ),
            "input_cache_write_tokens_1h": self._as_int(
                usage.get("input_cache_write_tokens_1h", 0)
            ),
            "input_cache_write_tokens_unknown": self._as_int(
                usage.get("input_cache_write_tokens_unknown", 0)
            ),
            "output_tokens": self._as_int(usage.get("output_tokens", 0)),
            "reasoning_tokens": self._as_int(usage.get("reasoning_tokens", 0)),
            "tool_input_tokens": self._as_int(usage.get("tool_input_tokens", 0)),
            "total_tokens": self._as_int(usage.get("total_tokens", 0)),
            "priced": bool(usage_cost.get("priced", False)),
            "cost_usd": usage_cost.get("total_cost_usd"),
            "pricing": usage_cost,
        }
        usage_store.append_record(enriched)
        return enriched

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
        llm = self._get_runtime_llm(runtime)

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
        llm = self._get_runtime_llm(runtime)

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
        llm = self._get_runtime_llm(runtime_state)

        rag_context = None
        if effective_runtime.rag_mode:
            results = runtime_state.memory_indexer.retrieve(
                message,
                settings=effective_runtime.retrieval.memory,
            )
            if results:
                rag_context = "[Memory Retrieval Results]\n" + "\n".join(
                    f"- ({item['score']}) {item['text']}" for item in results
                )

        messages = self._build_messages(
            history=history, message=message, rag_context=rag_context
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

        run_id = str(uuid.uuid4())
        agent, active_model = self._build_agent(
            llm=llm,
            runtime=effective_runtime,
            system_prompt=system_prompt,
            trigger_type=trigger_type,
            run_id=run_id,
            session_id=session_id,
            runtime_root=runtime_state.root_dir,
            runtime_audit_store=runtime_state.audit_store,
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
            base_url=self.config.secrets.deepseek_base_url,
        )
        usage_state: dict[str, Any] = {
            "provider": default_provider,
            "model": active_model,
            "model_source": "fallback_model",
            "usage_source": "unknown",
            "input_tokens": 0,
            "input_uncached_tokens": 0,
            "input_cache_read_tokens": 0,
            "input_cache_write_tokens_5m": 0,
            "input_cache_write_tokens_1h": 0,
            "input_cache_write_tokens_unknown": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "tool_input_tokens": 0,
            "total_tokens": 0,
        }
        usage_sources: dict[str, dict[str, int]] = {}

        captured_messages = usage_capture.snapshot()
        self._accumulate_usage_from_messages(
            usage_state=usage_state,
            usage_sources=usage_sources,
            messages=captured_messages,
            source_prefix=f"llm_end:{run_id}",
            fallback_model=active_model,
        )

        output_messages = result.get("messages", [])
        if isinstance(output_messages, list) and self._as_int(
            usage_state.get("total_tokens", 0)
        ) <= 0:
            # Fallback for providers/environments where callback payloads are sparse.
            self._accumulate_usage_from_messages(
                usage_state=usage_state,
                usage_sources=usage_sources,
                messages=output_messages,
                source_prefix=f"result:{run_id}",
                fallback_model=active_model,
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
            text = self._as_text(getattr(output_messages[-1], "content", ""))
        return {"text": text, "messages": output_messages, "usage": usage_payload or {}}

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
        llm = self._get_runtime_llm(runtime_state)

        rag_mode = effective_runtime.rag_mode
        rag_context = None
        if rag_mode:
            results = runtime_state.memory_indexer.retrieve(
                message,
                settings=effective_runtime.retrieval.memory,
            )
            yield {"type": "retrieval", "data": {"query": message, "results": results}}
            if results:
                rag_context = "[Memory Retrieval Results]\n" + "\n".join(
                    f"- ({item['score']}) {item['text']}" for item in results
                )

        system_prompt = self.build_system_prompt(
            rag_mode=rag_mode, is_first_turn=is_first_turn, agent_id=agent_id
        )
        messages = self._build_messages(
            history=history, message=message, rag_context=rag_context
        )

        pending_new_response = False
        final_tokens: list[str] = []
        fallback_final_text = ""
        token_source: str | None = None
        latest_model_snapshot = ""
        emitted_reasoning: set[str] = set()
        emitted_agent_update = False
        default_provider = infer_provider(
            self.config.secrets.deepseek_model,
            base_url=self.config.secrets.deepseek_base_url,
        )
        usage_state: dict[str, Any] = {
            "provider": default_provider,
            "model": self.config.secrets.deepseek_model,
            "model_source": "fallback_model",
            "usage_source": "unknown",
            "input_tokens": 0,
            "input_uncached_tokens": 0,
            "input_cache_read_tokens": 0,
            "input_cache_write_tokens_5m": 0,
            "input_cache_write_tokens_1h": 0,
            "input_cache_write_tokens_unknown": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "tool_input_tokens": 0,
            "total_tokens": 0,
        }
        usage_sources: dict[str, dict[str, int]] = {}
        usage_signature = ""

        for attempt in range(effective_runtime.agent_runtime.max_retries + 1):
            run_id = str(uuid.uuid4())
            try:
                yield {
                    "type": "run_start",
                    "data": {"run_id": run_id, "attempt": attempt + 1},
                }
                agent, active_model = self._build_agent(
                    llm=llm,
                    runtime=effective_runtime,
                    system_prompt=system_prompt,
                    trigger_type=trigger_type,
                    run_id=run_id,
                    session_id=session_id,
                    runtime_root=runtime_state.root_dir,
                    runtime_audit_store=runtime_state.audit_store,
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
                    base_url=self.config.secrets.deepseek_base_url,
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
                            emitted_agent_update = True

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
                                        fallback_final_text = content
                                        if token_source is None:
                                            delta = self._diff_incremental(
                                                latest_model_snapshot, content
                                            )
                                            latest_model_snapshot = content
                                            if delta:
                                                if pending_new_response:
                                                    yield {
                                                        "type": "new_response",
                                                        "data": {},
                                                    }
                                                    pending_new_response = False
                                                token_source = "updates"
                                                final_tokens.append(delta)
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
                                            or normalized in emitted_reasoning
                                        ):
                                            continue
                                        emitted_reasoning.add(normalized)
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
                                                    tool_msg, "tool_call_id", "tool"
                                                )
                                            ),
                                            "output": self._as_text(
                                                getattr(tool_msg, "content", "")
                                            ),
                                        },
                                    }
                                    pending_new_response = True

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

                        if token_source not in {None, "messages"}:
                            continue

                        if not emitted_agent_update:
                            yield {
                                "type": "agent_update",
                                "data": {
                                    "run_id": run_id,
                                    "node": "model",
                                    "message_count": 1,
                                    "preview": "Streaming token output",
                                },
                            }
                            emitted_agent_update = True

                        for text in self._extract_token_text(token):
                            if not text:
                                continue
                            token_source = "messages"
                            if pending_new_response:
                                yield {"type": "new_response", "data": {}}
                                pending_new_response = False
                            final_tokens.append(text)
                            yield {
                                "type": "token",
                                "data": {"content": text, "source": "messages"},
                            }

                    captured_messages = usage_capture.snapshot()
                    if usage_capture_offset < len(captured_messages):
                        usage_changed = self._accumulate_usage_from_messages(
                            usage_state=usage_state,
                            usage_sources=usage_sources,
                            messages=captured_messages[usage_capture_offset:],
                            source_prefix=f"llm_end:{run_id}",
                            fallback_model=active_model,
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
                                        usage_state.get("input_uncached_tokens", 0)
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
                                        "model": usage_state.get("model", "unknown"),
                                        **usage_state,
                                        "pricing": cost,
                                        "priced": bool(cost.get("priced", False)),
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
                        source_offset=usage_capture_offset,
                    )
                    usage_capture_offset = len(captured_messages)

                final_content = "".join(final_tokens).strip() or fallback_final_text
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
                        "token_source": token_source or "fallback",
                        "usage": enriched_usage,
                    },
                }
                return

            except Exception as exc:  # noqa: BLE001
                if attempt < effective_runtime.agent_runtime.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                yield {
                    "type": "error",
                    "data": {
                        "error": str(exc),
                        "run_id": run_id,
                        "attempt": attempt + 1,
                    },
                }
                return
