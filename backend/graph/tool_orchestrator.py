from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from config import LLMProfile, RuntimeConfig
from storage.run_store import AuditStore
from tools import (
    get_all_tools,
    get_explicit_blocked_tools,
    get_explicit_enabled_tools,
    get_tool_runner,
)
from tools.base import ToolContext
from tools.langchain_tools import build_langchain_tools


@dataclass
class BuiltAgent:
    agent: Any
    selected_model: str


class ToolOrchestrator:
    @staticmethod
    def build_agent(
        *,
        config_base_dir: Path,
        runtime_root: Path,
        runtime: RuntimeConfig,
        llm: ChatOpenAI,
        llm_profile: LLMProfile,
        trigger_type: str,
        run_id: str,
        session_id: str,
        runtime_audit_store: AuditStore,
        system_prompt: str,
        response_format: Any | None,
        resolve_tool_loop_model: Callable[[str, bool], str],
        build_llm_kwargs: Callable[..., dict[str, Any]],
    ) -> BuiltAgent:
        mini_tools = get_all_tools(
            runtime_root,
            runtime,
            trigger_type,
            config_base_dir=config_base_dir,
        )
        explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
        explicit_blocked_tools = get_explicit_blocked_tools(runtime, trigger_type)
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
                explicit_blocked_tools=tuple(explicit_blocked_tools),
                run_id=run_id,
                session_id=session_id,
            ),
        )

        configured_model = str(llm_profile.model)
        selected_model = resolve_tool_loop_model(
            configured_model,
            bool(langchain_tools),
        )

        active_llm = llm
        if selected_model != configured_model:
            active_llm = ChatOpenAI(
                **build_llm_kwargs(
                    profile=llm_profile,
                    runtime=runtime,
                    model_override=selected_model,
                )
            )

        if response_format is None:
            return BuiltAgent(
                agent=create_agent(
                    model=active_llm,
                    tools=langchain_tools,
                    system_prompt=system_prompt,
                ),
                selected_model=selected_model,
            )

        return BuiltAgent(
            agent=create_agent(
                model=active_llm,
                tools=langchain_tools,
                system_prompt=system_prompt,
                response_format=response_format,
            ),
            selected_model=selected_model,
        )
