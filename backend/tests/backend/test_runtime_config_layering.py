from __future__ import annotations

import json
import time
from pathlib import Path

from config import LlmRuntimeConfig, RetrievalConfig, RuntimeConfig, load_effective_runtime_config, merge_runtime_configs
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
                "retrieval": {"memory": {"top_k": 6, "semantic_weight": 0.8, "lexical_weight": 0.2}},
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
        retrieval=RetrievalConfig(),
    )
    override = RuntimeConfig(llm_runtime=LlmRuntimeConfig(temperature=0.5, timeout_seconds=60))

    merged = merge_runtime_configs(base, override)
    assert merged.rag_mode is True
    assert merged.llm_runtime.temperature == 0.5
    # Because override timeout matches baseline default, base timeout should be retained.
    assert merged.llm_runtime.timeout_seconds == 120


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
    (base_dir / "config.json").write_text(json.dumps({"rag_mode": False}) + "\n", encoding="utf-8")
    manager = _seed_manager_dirs(base_dir)

    alpha = manager.get_runtime("alpha")
    beta = manager.get_runtime("beta")
    (beta.root_dir / "config.json").write_text(json.dumps({"rag_mode": True}) + "\n", encoding="utf-8")
    time.sleep(0.01)

    alpha_after = manager.get_runtime("alpha")
    beta_after = manager.get_runtime("beta")
    assert alpha_after.runtime_config.rag_mode is False
    assert beta_after.runtime_config.rag_mode is True
