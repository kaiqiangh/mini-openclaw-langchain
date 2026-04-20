from __future__ import annotations

import json
import time
from pathlib import Path

from config import (
    DelegationConfig,
    LlmRuntimeConfig,
    LlmRoutePatch,
    RetrievalConfig,
    RuntimeConfig,
    TerminalCommandPolicyMode,
    TerminalSandboxMode,
    load_effective_runtime_config,
    merge_runtime_configs,
    runtime_from_payload,
    runtime_to_payload,
)
from graph.agent import AgentManager


def _seed_manager_dirs(base_dir: Path) -> AgentManager:
    workspaces_dir = base_dir / "workspaces"
    template_dir = base_dir / "workspace-template"
    (template_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (template_dir / "memory").mkdir(parents=True, exist_ok=True)
    (template_dir / "knowledge").mkdir(parents=True, exist_ok=True)

    manager = AgentManager()
    manager.base_dir = base_dir
    manager.workspaces_dir = workspaces_dir
    manager.workspace_template_dir = template_dir
    return manager


def test_load_effective_runtime_config_deep_merge(tmp_path: Path):
    global_config = tmp_path / "global.json"
    agent_config = tmp_path / "agent.json"
    global_config.write_text(
        json.dumps(
            {
                "rag_mode": False,
                "llm_runtime": {"temperature": 0.4, "timeout_seconds": 45},
                "retrieval": {
                    "memory": {
                        "top_k": 6,
                        "semantic_weight": 0.8,
                        "lexical_weight": 0.2,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    agent_config.write_text(
        json.dumps(
            {
                "llm_runtime": {"temperature": 0.9},
                "agent_runtime": {"max_steps": 9},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    merged = load_effective_runtime_config(global_config, agent_config)
    assert merged.rag_mode is False
    assert merged.llm_runtime.temperature == 0.9
    assert merged.llm_runtime.timeout_seconds == 45
    assert merged.agent_runtime.max_steps == 9
    assert merged.retrieval.memory.top_k == 6
    assert merged.retrieval.memory.semantic_weight == 0.8
    assert merged.retrieval.memory.lexical_weight == 0.2


def test_merge_runtime_configs_uses_override_delta():
    base = RuntimeConfig(
        rag_mode=True,
        llm_runtime=LlmRuntimeConfig(temperature=0.15, timeout_seconds=120),
        llm=LlmRoutePatch(
            default="openai",
            fallbacks=["deepseek"],
            tool_loop_model="gpt-4.1-mini",
            tool_loop_model_overrides={"gpt-5-mini": "gpt-4.1-mini"},
        ),
        retrieval=RetrievalConfig(),
    )
    override = RuntimeConfig(llm_runtime=LlmRuntimeConfig(temperature=0.5))

    merged = merge_runtime_configs(base, override)
    assert merged.rag_mode is True
    assert merged.llm_runtime.temperature == 0.5
    # Because override timeout matches baseline default, base timeout should be retained.
    assert merged.llm_runtime.timeout_seconds == 120
    assert merged.llm.default == "openai"
    assert merged.llm.fallbacks == ["deepseek"]
    assert merged.llm.tool_loop_model == "gpt-4.1-mini"
    assert merged.llm.tool_loop_model_overrides == {
        "gpt-5-mini": "gpt-4.1-mini"
    }


def test_agent_runtime_auto_reload_on_agent_config_change(tmp_path: Path):
    base_dir = tmp_path
    (base_dir / "config.json").write_text(
        json.dumps({"rag_mode": False, "agent_runtime": {"max_steps": 20}}) + "\n",
        encoding="utf-8",
    )
    manager = _seed_manager_dirs(base_dir)

    runtime = manager.get_runtime("alpha")
    first_digest = runtime.runtime_config_digest
    first_obj_id = id(runtime.runtime_config)
    assert runtime.runtime_config.agent_runtime.max_steps == 20

    agent_config = runtime.root_dir / "config.json"
    agent_config.write_text(
        json.dumps({"rag_mode": True, "agent_runtime": {"max_steps": 7}}) + "\n",
        encoding="utf-8",
    )
    time.sleep(0.01)

    refreshed = manager.get_runtime("alpha")
    assert refreshed is runtime
    assert refreshed.runtime_config.rag_mode is True
    assert refreshed.runtime_config.agent_runtime.max_steps == 7
    assert refreshed.runtime_config_digest != first_digest

    unchanged = manager.get_runtime("alpha")
    assert unchanged.runtime_config_digest == refreshed.runtime_config_digest
    assert id(unchanged.runtime_config) == id(refreshed.runtime_config)
    assert id(unchanged.runtime_config) != first_obj_id


def test_agent_runtime_isolation_between_agents(tmp_path: Path):
    base_dir = tmp_path
    (base_dir / "config.json").write_text(
        json.dumps({"rag_mode": False}) + "\n", encoding="utf-8"
    )
    manager = _seed_manager_dirs(base_dir)

    alpha = manager.get_runtime("alpha")
    beta = manager.get_runtime("beta")
    (beta.root_dir / "config.json").write_text(
        json.dumps({"rag_mode": True}) + "\n", encoding="utf-8"
    )
    time.sleep(0.01)

    alpha_after = manager.get_runtime("alpha")
    beta_after = manager.get_runtime("beta")
    assert alpha_after.runtime_config.rag_mode is False
    assert beta_after.runtime_config.rag_mode is True


def test_runtime_config_round_trip_preserves_terminal_execution_settings():
    runtime = RuntimeConfig()
    runtime.chat_enabled_tools = ["terminal"]
    runtime.chat_blocked_tools = ["read_files"]
    runtime.delegation = DelegationConfig(
        enabled=True,
        max_per_session=3,
        default_timeout_seconds=45,
        max_timeout_seconds=90,
        allowed_tool_scopes={
            "researcher": ["web_search", "fetch_url"],
            "writer": ["read_files", "apply_patch"],
        },
    )
    runtime.llm = LlmRoutePatch(
        default="azure_foundry",
        fallbacks=[],
        tool_loop_model="gpt-4.1-mini",
        tool_loop_model_overrides={"gpt-5-mini": "gpt-4.1-mini"},
    )
    runtime.tool_execution.terminal.sandbox_mode = TerminalSandboxMode.UNSAFE_NONE
    runtime.tool_execution.terminal.command_policy_mode = (
        TerminalCommandPolicyMode.DENYLIST
    )
    runtime.tool_execution.terminal.require_sandbox = False
    runtime.tool_execution.terminal.allowed_command_prefixes = ["echo", "python3 -c"]
    runtime.tool_execution.terminal.denied_command_prefixes = ["date"]
    runtime.tool_execution.terminal.allow_network = True
    runtime.tool_execution.terminal.allow_shell_syntax = True
    runtime.tool_execution.terminal.max_args = 12
    runtime.tool_execution.terminal.max_arg_length = 64

    payload = runtime_to_payload(runtime)
    loaded = runtime_from_payload(payload)

    assert loaded.chat_enabled_tools == ["terminal"]
    assert loaded.chat_blocked_tools == ["read_files"]
    assert loaded.delegation.enabled is True
    assert loaded.delegation.max_per_session == 3
    assert loaded.delegation.default_timeout_seconds == 45
    assert loaded.delegation.max_timeout_seconds == 90
    assert loaded.delegation.allowed_tool_scopes == {
        "researcher": ["web_search", "fetch_url"],
        "writer": ["read_files", "apply_patch"],
    }
    assert loaded.llm.default == "azure_foundry"
    assert loaded.llm.fallbacks == []
    assert loaded.llm.tool_loop_model == "gpt-4.1-mini"
    assert loaded.llm.tool_loop_model_overrides == {
        "gpt-5-mini": "gpt-4.1-mini"
    }
    assert loaded.tool_execution.terminal.sandbox_mode == TerminalSandboxMode.UNSAFE_NONE
    assert (
        loaded.tool_execution.terminal.command_policy_mode
        == TerminalCommandPolicyMode.DENYLIST
    )
    assert loaded.tool_execution.terminal.require_sandbox is False
    assert loaded.tool_execution.terminal.allowed_command_prefixes == [
        "echo",
        "python3 -c",
    ]
    assert loaded.tool_execution.terminal.denied_command_prefixes == ["date"]
    assert loaded.tool_execution.terminal.allow_network is True
    assert loaded.tool_execution.terminal.allow_shell_syntax is True
    assert loaded.tool_execution.terminal.max_args == 12
    assert loaded.tool_execution.terminal.max_arg_length == 64


def test_runtime_from_payload_infers_terminal_policy_mode_from_allowlist_presence():
    allowlisted = runtime_from_payload(
        {
            "tool_execution": {
                "terminal": {
                    "allowed_command_prefixes": ["echo"],
                }
            }
        }
    )
    assert (
        allowlisted.tool_execution.terminal.command_policy_mode
        == TerminalCommandPolicyMode.ALLOWLIST
    )

    automatic = runtime_from_payload(
        {
            "tool_execution": {
                "terminal": {
                    "allowed_command_prefixes": [],
                }
            }
        }
    )
    assert (
        automatic.tool_execution.terminal.command_policy_mode
        == TerminalCommandPolicyMode.ALLOWLIST
    )

    inferred_auto = runtime_from_payload(
        {
            "tool_execution": {
                "terminal": {}
            }
        }
    )
    assert (
        inferred_auto.tool_execution.terminal.command_policy_mode
        == TerminalCommandPolicyMode.AUTO
    )


def test_runtime_from_payload_rejects_legacy_llm_profile():
    payload = {
        "llm_runtime": {
            "temperature": 0.2,
            "timeout_seconds": 60,
            "profile": "openai",
        }
    }

    try:
        runtime_from_payload(payload)
    except ValueError as exc:
        assert "llm_runtime.profile" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("legacy llm_runtime.profile should be rejected")
