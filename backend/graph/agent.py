from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

from config import (
    AppConfig,
    RuntimeConfig,
    load_config,
    load_effective_runtime_config,
    runtime_config_digest,
)
from graph.graph_registry import GraphRuntimeRegistry
from graph.lcel_pipelines import RuntimeLcelPipelines
from graph.memory_indexer import MemoryIndexer
from graph.prompt_builder import PromptBuilder
from graph.runtime_types import RuntimeRequest, ToolCapableChatModel
from graph.session_manager import SessionManager
from graph.skill_selector import SkillSelector
from graph.usage_orchestrator import UsageOrchestrator
from storage.run_store import AuditStore
from storage.usage_store import UsageStore
from tools.skills_scanner import ensure_skills_snapshot

if TYPE_CHECKING:
    from graph.checkpoint_session_repository import CheckpointSessionRepository

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
    llm_cache: dict[tuple[float, int, str, str, str, str, str], ToolCapableChatModel] = (
        field(default_factory=dict)
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
        self.skill_selector = SkillSelector()
        self.usage_orchestrator = UsageOrchestrator()
        self.lcel_pipelines = RuntimeLcelPipelines()
        from graph.checkpoint_session_repository import CheckpointSessionRepository
        from graph.default_graph_runtime import DefaultGraphRuntime
        from graph.runtime_execution_services import RuntimeExecutionServices
        from graph.sqlite_runtime_checkpointer import SQLiteRuntimeCheckpointer

        self.runtime_services = RuntimeExecutionServices(
            base_dir_getter=lambda: self.base_dir,
            app_config_getter=self._refresh_app_config,
            runtime_getter=self.get_runtime,
            prompt_builder=self.prompt_builder,
            usage_orchestrator=self.usage_orchestrator,
        )
        self.runtime_checkpointer = SQLiteRuntimeCheckpointer(
            runtime_getter=self.get_runtime
        )
        self.graph_registry = GraphRuntimeRegistry(checkpointer=self.runtime_checkpointer)
        self.graph_registry.register(
            "default",
            lambda: DefaultGraphRuntime(
                services=self.runtime_services,
                pipelines=self.lcel_pipelines,
                skill_selector=self.skill_selector,
                checkpointer=self.runtime_checkpointer,
            ),
        )
        self.session_repository = CheckpointSessionRepository(
            runtime_getter=self.get_runtime,
            graph_getter=self._runtime_graph,
            checkpointer=self.runtime_checkpointer,
        )
        self.runtime_services.set_session_repository(self.session_repository)
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

    def get_session_repository(
        self, agent_id: str = "default"
    ) -> CheckpointSessionRepository:
        _ = agent_id
        return self.session_repository

    def get_memory_indexer(self, agent_id: str = "default") -> MemoryIndexer:
        return self.get_runtime(agent_id).memory_indexer

    def get_usage_store(self, agent_id: str = "default") -> UsageStore:
        return self.get_runtime(agent_id).usage_store

    def get_llm_status(self, agent_id: str = "default") -> dict[str, Any]:
        runtime = self.get_runtime(agent_id)
        return self.runtime_services.resolve_llm_route(runtime).to_status_dict()

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

    def _runtime_graph(self, graph_name: str = "default") -> Any:
        return self.graph_registry.resolve(graph_name)

    async def get_graph_state(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        graph_name: str = "default",
    ) -> dict[str, Any]:
        return await self.session_repository.get_state(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )

    async def get_graph_state_history(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        graph_name: str = "default",
    ) -> list[dict[str, Any]]:
        return await self.session_repository.get_state_history(
            agent_id=agent_id,
            session_id=session_id,
            graph_name=graph_name,
        )

    async def update_graph_state(
        self,
        *,
        session_id: str,
        values: dict[str, Any],
        agent_id: str = "default",
        graph_name: str = "default",
    ) -> dict[str, Any]:
        return await self.session_repository.update_state(
            agent_id=agent_id,
            session_id=session_id,
            values=values,
            graph_name=graph_name,
        )

    async def generate_title(self, seed_text: str, agent_id: str = "default") -> str:
        if self.config is None:
            return seed_text[:10] or "New Session"
        runtime = self.get_runtime(agent_id)
        candidate = self.runtime_services.resolve_auxiliary_llm_candidate(runtime)
        if candidate is None:
            return seed_text[:40] or "New Session"
        llm = self.runtime_services.get_runtime_llm(runtime, candidate.profile)

        try:
            chain = self.lcel_pipelines.title_chain(llm=llm)
            response = await chain.ainvoke({"seed_text": seed_text[:200]})
            first_line = str(response).strip().splitlines()[0]
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
        candidate = self.runtime_services.resolve_auxiliary_llm_candidate(runtime)
        if candidate is None:
            corpus = "\n".join(
                f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}"
                for m in messages
            )
            return corpus[:500]
        llm = self.runtime_services.get_runtime_llm(runtime, candidate.profile)

        corpus = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}"
            for m in messages
        )
        try:
            chain = self.lcel_pipelines.summary_chain(llm=llm)
            summary = str(await chain.ainvoke({"corpus": corpus[:4000]})).strip()
            return summary[:500]
        except Exception:  # noqa: BLE001
            return corpus[:500]

    def build_system_prompt(
        self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default"
    ) -> str:
        if self.config is None:
            raise RuntimeError("AgentManager is not initialized")
        return self.runtime_services.build_system_prompt(
            rag_mode=rag_mode,
            is_first_turn=is_first_turn,
            agent_id=agent_id,
        )

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
        resume_same_turn: bool = False,
    ) -> dict[str, Any]:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager must be initialized before run_once().")
        result = await self._runtime_graph().invoke(
            RuntimeRequest(
                message=message,
                history=history,
                session_id=session_id,
                is_first_turn=is_first_turn,
                output_format=output_format,
                trigger_type=trigger_type,
                agent_id=agent_id,
                resume_same_turn=resume_same_turn,
            )
        )
        if result.error is not None:
            raise RuntimeError(result.error.error)
        if output_format == "json":
            return {
                "structured_response": result.structured_response,
                "messages": result.messages,
                "selected_skills": result.selected_skills,
                "usage": result.usage,
                "run_id": result.run_id,
            }
        return {
            "text": result.text,
            "messages": result.messages,
            "selected_skills": result.selected_skills,
            "usage": result.usage,
            "run_id": result.run_id,
        }

    async def astream(
        self,
        message: str,
        history: list[dict[str, Any]],
        session_id: str,
        is_first_turn: bool = False,
        trigger_type: str = "chat",
        agent_id: str = "default",
        resume_same_turn: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not self.base_dir or not self.config:
            raise RuntimeError("AgentManager must be initialized before astream().")
        runtime = self._runtime_graph()
        async for event in runtime.astream(
            RuntimeRequest(
                message=message,
                history=history,
                session_id=session_id,
                is_first_turn=is_first_turn,
                output_format="text",
                trigger_type=trigger_type,
                agent_id=agent_id,
                resume_same_turn=resume_same_turn,
            )
        ):
            yield event.as_payload()
