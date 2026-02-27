from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import AppConfig, RuntimeConfig, load_config
from graph.callbacks import AuditCallbackHandler
from graph.memory_indexer import MemoryIndexer
from graph.prompt_builder import PromptBuilder
from graph.session_manager import SessionManager
from observability.tracing import build_optional_callbacks
from storage.run_store import AuditStore
from storage.usage_store import UsageStore
from tools import get_all_tools, get_explicit_enabled_tools, get_tool_runner
from tools.base import ToolContext
from tools.langchain_tools import build_langchain_tools
from usage.pricing import estimate_cost_usd

_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class AgentRuntime:
    agent_id: str
    root_dir: Path
    session_manager: SessionManager
    memory_indexer: MemoryIndexer
    audit_store: AuditStore
    usage_store: UsageStore


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
        self._llm: ChatOpenAI | None = None
        self.max_steps = 20
        self.max_retries = 1
        self.default_agent_id = "default"
        self._runtimes: dict[str, AgentRuntime] = {}

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.workspaces_dir = base_dir / "workspaces"
        self.workspace_template_dir = base_dir / "workspace-template"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_template_dir.mkdir(parents=True, exist_ok=True)

        self.config = load_config(base_dir)
        self._llm = self._build_llm(self.config)

        self._ensure_workspace_template()
        self._ensure_workspace(self.default_agent_id)
        default_runtime = self.get_runtime(self.default_agent_id)
        self.session_manager = default_runtime.session_manager
        self.memory_indexer = default_runtime.memory_indexer
        self.audit_store = default_runtime.audit_store
        self.usage_store = default_runtime.usage_store

    @staticmethod
    def _build_llm(config: AppConfig) -> ChatOpenAI:
        return ChatOpenAI(
            model=config.secrets.deepseek_model,
            api_key=config.secrets.deepseek_api_key,
            base_url=config.secrets.deepseek_base_url,
            temperature=0.2,
            timeout=60,
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

    def _copy_text_if_missing(self, source: Path | None, target: Path, default_text: str = "") -> None:
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
            target.write_text("<available_skills>\n</available_skills>\n", encoding="utf-8")

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
                default_usage.write_text(legacy_usage.read_text(encoding="utf-8"), encoding="utf-8")

            legacy_knowledge = self.base_dir / "knowledge"
            default_knowledge = root / "knowledge"
            if legacy_knowledge.exists() and not any(default_knowledge.rglob("*")):
                shutil.copytree(legacy_knowledge, default_knowledge, dirs_exist_ok=True)

        self._sync_skills_snapshot(root)
        return root

    def _build_runtime(self, agent_id: str) -> AgentRuntime:
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        workspace_root = self._ensure_workspace(agent_id)
        runtime = AgentRuntime(
            agent_id=agent_id,
            root_dir=workspace_root,
            session_manager=SessionManager(workspace_root),
            memory_indexer=MemoryIndexer(workspace_root, config_base_dir=self.base_dir),
            audit_store=AuditStore(workspace_root),
            usage_store=UsageStore(workspace_root),
        )
        runtime.audit_store.ensure_schema_descriptor()
        return runtime

    def get_runtime(self, agent_id: str = "default") -> AgentRuntime:
        normalized = self._normalize_agent_id(agent_id)
        runtime = self._runtimes.get(normalized)
        if runtime is not None:
            return runtime
        runtime = self._build_runtime(normalized)
        self._runtimes[normalized] = runtime
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
            active_sessions = len([p for p in sessions_dir.glob("*.json") if p.is_file()]) if sessions_dir.exists() else 0
            archived_dir = sessions_dir / "archived_sessions"
            archived_sessions = len([p for p in archived_dir.glob("*.json") if p.is_file()]) if archived_dir.exists() else 0
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
        runtime.memory_indexer.rebuild_index()
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
    ) -> list[Any]:
        callback = AuditCallbackHandler(
            audit_file=runtime_root / "storage" / "runs_events.jsonl",
            run_id=run_id,
            session_id=session_id,
            trigger_type=trigger_type,
            audit_store=runtime_audit_store,
        )
        # Internal audit callback is always enabled; external tracing is optional.
        return [callback, *build_optional_callbacks(run_id=run_id)]

    def _build_agent(
        self,
        *,
        runtime: RuntimeConfig,
        system_prompt: str,
        trigger_type: str,
        run_id: str,
        session_id: str,
        runtime_root: Path,
        runtime_audit_store: AuditStore,
        response_format: Any | None = None,
    ) -> Any:
        if self.base_dir is None or self._llm is None:
            raise RuntimeError("AgentManager is not initialized")

        mini_tools = get_all_tools(
            runtime_root,
            runtime,
            trigger_type,
            config_base_dir=self.base_dir,
        )
        explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
        runner = get_tool_runner(runtime_root, runtime_audit_store)
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

        if response_format is None:
            return create_agent(
                model=self._llm,
                tools=langchain_tools,
                system_prompt=system_prompt,
            )

        return create_agent(
            model=self._llm,
            tools=langchain_tools,
            system_prompt=system_prompt,
            response_format=response_format,
        )

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
            if btype not in {"reasoning", "reasoning_chunk", "thinking", "thinking_chunk"}:
                continue
            text = block.get("text") or block.get("content") or block.get("reasoning") or ""
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

    def _extract_usage_from_message(self, message: Any) -> dict[str, Any]:
        usage: dict[str, Any] = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }

        usage_metadata = self._as_dict(getattr(message, "usage_metadata", None))
        if usage_metadata:
            usage["input_tokens"] = max(
                usage["input_tokens"],
                self._as_int(usage_metadata.get("input_tokens", usage_metadata.get("prompt_tokens", 0))),
            )
            usage["output_tokens"] = max(
                usage["output_tokens"],
                self._as_int(usage_metadata.get("output_tokens", usage_metadata.get("completion_tokens", 0))),
            )
            usage["total_tokens"] = max(
                usage["total_tokens"],
                self._as_int(usage_metadata.get("total_tokens", 0)),
            )

            input_details = self._as_dict(usage_metadata.get("input_token_details"))
            output_details = self._as_dict(usage_metadata.get("output_token_details"))
            usage["cached_input_tokens"] = max(
                usage["cached_input_tokens"],
                self._as_int(input_details.get("cache_read", input_details.get("cached_tokens", 0))),
            )
            usage["reasoning_tokens"] = max(
                usage["reasoning_tokens"],
                self._as_int(output_details.get("reasoning", output_details.get("reasoning_tokens", 0))),
            )

        response_metadata = self._as_dict(getattr(message, "response_metadata", None))
        token_usage = self._as_dict(response_metadata.get("token_usage", response_metadata.get("usage", {})))
        if token_usage:
            usage["input_tokens"] = max(
                usage["input_tokens"],
                self._as_int(token_usage.get("prompt_tokens", token_usage.get("input_tokens", 0))),
            )
            usage["output_tokens"] = max(
                usage["output_tokens"],
                self._as_int(token_usage.get("completion_tokens", token_usage.get("output_tokens", 0))),
            )
            usage["total_tokens"] = max(
                usage["total_tokens"],
                self._as_int(token_usage.get("total_tokens", 0)),
            )

            prompt_details = self._as_dict(token_usage.get("prompt_tokens_details"))
            completion_details = self._as_dict(token_usage.get("completion_tokens_details"))
            usage["cached_input_tokens"] = max(
                usage["cached_input_tokens"],
                self._as_int(prompt_details.get("cached_tokens", prompt_details.get("cache_read", 0))),
            )
            usage["reasoning_tokens"] = max(
                usage["reasoning_tokens"],
                self._as_int(completion_details.get("reasoning_tokens", completion_details.get("reasoning", 0))),
            )

        if usage["input_tokens"] == 0 and usage["total_tokens"] > 0:
            usage["input_tokens"] = max(0, usage["total_tokens"] - usage["output_tokens"])
        if usage["total_tokens"] == 0 and (usage["input_tokens"] or usage["output_tokens"]):
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        usage["cached_input_tokens"] = min(usage["cached_input_tokens"], usage["input_tokens"])
        usage["uncached_input_tokens"] = max(0, usage["input_tokens"] - usage["cached_input_tokens"])
        return usage

    def _record_usage(
        self,
        *,
        usage: dict[str, Any],
        run_id: str,
        session_id: str,
        trigger_type: str,
        model: str,
        agent_id: str,
        usage_store: UsageStore,
    ) -> dict[str, Any]:
        cost = estimate_cost_usd(
            model=model,
            input_tokens=self._as_int(usage.get("input_tokens", 0)),
            cached_input_tokens=self._as_int(usage.get("cached_input_tokens", 0)),
            output_tokens=self._as_int(usage.get("output_tokens", 0)),
        )
        enriched = {
            "agent_id": agent_id,
            "model": model,
            "trigger_type": trigger_type,
            "run_id": run_id,
            "session_id": session_id,
            **usage,
            **cost,
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

    async def generate_title(self, seed_text: str) -> str:
        if self._llm is None:
            return seed_text[:10] or "New Session"

        prompt = (
            "Generate a short session title in plain English, at most 10 words. "
            "No quotes and no trailing punctuation. Return only the title.\n"
            f"Content: {seed_text[:200]}"
        )
        try:
            response = await self._llm.ainvoke(prompt)
            first_line = str(getattr(response, "content", "")).strip().splitlines()[0]
            title = " ".join(first_line.split()[:10])[:80].strip()
            return title or (seed_text[:40] or "New Session")
        except Exception:  # noqa: BLE001
            return seed_text[:40] or "New Session"

    async def summarize_messages(self, messages: list[dict[str, Any]]) -> str:
        if self._llm is None:
            joined = "\n".join(f"{m.get('role','user')}: {m.get('content','')[:80]}" for m in messages)
            return joined[:500]

        corpus = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}" for m in messages
        )
        prompt = (
            "Summarize the following conversation in under 500 characters. "
            "Preserve key conclusions, user preferences, and unfinished tasks.\n"
            f"{corpus[:4000]}"
        )
        try:
            response = await self._llm.ainvoke(prompt)
            summary = str(getattr(response, "content", "")).strip()
            return summary[:500]
        except Exception:  # noqa: BLE001
            return corpus[:500]

    def build_system_prompt(self, *, rag_mode: bool, is_first_turn: bool, agent_id: str = "default") -> str:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager is not initialized")
        runtime = self.get_runtime(agent_id)
        self.config = load_config(self.base_dir)
        pack = self.prompt_builder.build_system_prompt(
            base_dir=runtime.root_dir,
            runtime=self.config.runtime,
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
        output_format: str = "text",
        trigger_type: str = "chat",
        agent_id: str = "default",
    ) -> dict[str, Any]:
        if self.base_dir is None or self.config is None:
            raise RuntimeError("AgentManager must be initialized before run_once().")
        runtime = self.get_runtime(agent_id)
        self.config = load_config(self.base_dir)

        rag_context = None
        if self.config.runtime.rag_mode:
            results = runtime.memory_indexer.retrieve(message, top_k=3)
            if results:
                rag_context = "[Memory Retrieval Results]\n" + "\n".join(
                    f"- ({item['score']}) {item['text']}" for item in results
                )

        messages = self._build_messages(history=history, message=message, rag_context=rag_context)
        system_prompt = self.build_system_prompt(
            rag_mode=self.config.runtime.rag_mode,
            is_first_turn=False,
            agent_id=agent_id,
        )

        response_schema = None
        if output_format == "json":
            from pydantic import BaseModel

            class RunJsonResponse(BaseModel):
                answer: str

            response_schema = RunJsonResponse

        run_id = str(uuid.uuid4())
        agent = self._build_agent(
            runtime=self.config.runtime,
            system_prompt=system_prompt,
            trigger_type=trigger_type,
            run_id=run_id,
            session_id=session_id,
            runtime_root=runtime.root_dir,
            runtime_audit_store=runtime.audit_store,
            response_format=response_schema,
        )

        config = {
            "recursion_limit": self.max_steps,
            "callbacks": self._build_callbacks(
                run_id=run_id,
                session_id=session_id,
                trigger_type=trigger_type,
                runtime_root=runtime.root_dir,
                runtime_audit_store=runtime.audit_store,
            ),
            "configurable": {"thread_id": session_id},
        }

        result = await agent.ainvoke({"messages": messages}, config=config)
        usage_payload: dict[str, Any] | None = None
        output_messages = result.get("messages", [])
        if isinstance(output_messages, list):
            for message_obj in reversed(output_messages):
                candidate = self._extract_usage_from_message(message_obj)
                if self._as_int(candidate.get("total_tokens", 0)) > 0:
                    usage_payload = self._record_usage(
                        usage=candidate,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        model=self.config.secrets.deepseek_model,
                        agent_id=agent_id,
                        usage_store=runtime.usage_store,
                    )
                    break

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
        runtime = self.get_runtime(agent_id)
        self.config = load_config(self.base_dir)

        rag_mode = self.config.runtime.rag_mode
        rag_context = None
        if rag_mode:
            results = runtime.memory_indexer.retrieve(message, top_k=3)
            yield {"type": "retrieval", "data": {"query": message, "results": results}}
            if results:
                rag_context = "[Memory Retrieval Results]\n" + "\n".join(
                    f"- ({item['score']}) {item['text']}" for item in results
                )

        system_prompt = self.build_system_prompt(rag_mode=rag_mode, is_first_turn=is_first_turn, agent_id=agent_id)
        messages = self._build_messages(history=history, message=message, rag_context=rag_context)

        pending_new_response = False
        final_tokens: list[str] = []
        fallback_final_text = ""
        token_source: str | None = None
        latest_model_snapshot = ""
        emitted_reasoning: set[str] = set()
        emitted_agent_update = False
        usage_state: dict[str, Any] = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
        usage_signature = ""

        for attempt in range(self.max_retries + 1):
            run_id = str(uuid.uuid4())
            try:
                yield {"type": "run_start", "data": {"run_id": run_id, "attempt": attempt + 1}}
                agent = self._build_agent(
                    runtime=self.config.runtime,
                    system_prompt=system_prompt,
                    trigger_type=trigger_type,
                    run_id=run_id,
                    session_id=session_id,
                    runtime_root=runtime.root_dir,
                    runtime_audit_store=runtime.audit_store,
                )

                config = {
                    "recursion_limit": self.max_steps,
                    "callbacks": self._build_callbacks(
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        runtime_root=runtime.root_dir,
                        runtime_audit_store=runtime.audit_store,
                    ),
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
                                    "preview": self._as_text(getattr(latest, "content", ""))[:500],
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
                                                "tool": str(call.get("name", "unknown")),
                                                "input": call.get("args", {}),
                                            },
                                        }
                                else:
                                    content = self._as_text(getattr(latest, "content", ""))
                                    if content:
                                        fallback_final_text = content
                                        if token_source is None:
                                            delta = self._diff_incremental(latest_model_snapshot, content)
                                            latest_model_snapshot = content
                                            if delta:
                                                if pending_new_response:
                                                    yield {"type": "new_response", "data": {}}
                                                    pending_new_response = False
                                                token_source = "updates"
                                                final_tokens.append(delta)
                                                yield {"type": "token", "data": {"content": delta, "source": "updates"}}

                                    for reasoning in self._extract_reasoning_text(latest):
                                        normalized = reasoning.strip()
                                        if not normalized or normalized in emitted_reasoning:
                                            continue
                                        emitted_reasoning.add(normalized)
                                        yield {
                                            "type": "reasoning",
                                            "data": {
                                                "run_id": run_id,
                                                "content": normalized[:1000],
                                            },
                                        }

                                usage_candidate = self._extract_usage_from_message(latest)
                                if self._as_int(usage_candidate.get("total_tokens", 0)) > 0:
                                    for key in usage_state.keys():
                                        usage_state[key] = max(
                                            self._as_int(usage_state.get(key, 0)),
                                            self._as_int(usage_candidate.get(key, 0)),
                                        )
                                    signature = "|".join(str(usage_state.get(k, 0)) for k in sorted(usage_state))
                                    if signature != usage_signature:
                                        usage_signature = signature
                                        cost = estimate_cost_usd(
                                            model=self.config.secrets.deepseek_model,
                                            input_tokens=self._as_int(usage_state.get("input_tokens", 0)),
                                            cached_input_tokens=self._as_int(
                                                usage_state.get("cached_input_tokens", 0)
                                            ),
                                            output_tokens=self._as_int(usage_state.get("output_tokens", 0)),
                                        )
                                        yield {
                                            "type": "usage",
                                            "data": {
                                                "run_id": run_id,
                                                "agent_id": agent_id,
                                                "model": self.config.secrets.deepseek_model,
                                                **usage_state,
                                                **cost,
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
                                                or getattr(tool_msg, "tool_call_id", "tool")
                                            ),
                                            "output": self._as_text(getattr(tool_msg, "content", "")),
                                        },
                                    }
                                    pending_new_response = True

                    if mode == "messages" and isinstance(chunk, tuple) and len(chunk) == 2:
                        token, metadata = chunk
                        node = metadata.get("langgraph_node", "") if isinstance(metadata, dict) else ""
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
                            yield {"type": "token", "data": {"content": text, "source": "messages"}}

                        usage_candidate = self._extract_usage_from_message(token)
                        if self._as_int(usage_candidate.get("total_tokens", 0)) > 0:
                            for key in usage_state.keys():
                                usage_state[key] = max(
                                    self._as_int(usage_state.get(key, 0)),
                                    self._as_int(usage_candidate.get(key, 0)),
                                )

                final_content = "".join(final_tokens).strip() or fallback_final_text
                enriched_usage = {}
                if self._as_int(usage_state.get("total_tokens", 0)) > 0:
                    enriched_usage = self._record_usage(
                        usage=usage_state,
                        run_id=run_id,
                        session_id=session_id,
                        trigger_type=trigger_type,
                        model=self.config.secrets.deepseek_model,
                        agent_id=agent_id,
                        usage_store=runtime.usage_store,
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
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                yield {
                    "type": "error",
                    "data": {"error": str(exc), "run_id": run_id, "attempt": attempt + 1},
                }
                return
