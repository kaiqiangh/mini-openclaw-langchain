from __future__ import annotations

import json
from pathlib import Path

from config import load_config, load_effective_runtime_config, validate_required_secrets
from llm_routing import resolve_agent_llm_route
from usage.pricing import infer_provider


def _write_config(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")


def test_validate_required_secrets_only_checks_global_boot_blockers(
    monkeypatch, tmp_path: Path
):
    _write_config(
        tmp_path / "config.json",
        {"llm_defaults": {"default": "openai", "fallbacks": ["deepseek"]}},
    )
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    loaded = load_config(tmp_path)
    assert validate_required_secrets(loaded) == ["APP_ADMIN_TOKEN"]

    monkeypatch.setenv("APP_ADMIN_TOKEN", "token-1")
    assert validate_required_secrets(load_config(tmp_path)) == []


def test_load_config_parses_llm_defaults_and_agent_overrides(tmp_path: Path):
    _write_config(
        tmp_path / "config.json",
        {
            "llm_defaults": {
                "default": "deepseek",
                "fallbacks": ["openai"],
                "tool_loop_model": "deepseek-chat",
                "tool_loop_model_overrides": {
                    "deepseek-reasoner": "deepseek-chat",
                },
                "fallback_policy": {"on_timeout": "fallback"},
            },
            "agent_llm_overrides": {
                "crypto": {
                    "default": "azure_foundry",
                    "fallbacks": [],
                    "tool_loop_model": "gpt-4.1-mini",
                    "tool_loop_model_overrides": {
                        "gpt-5-mini": "gpt-4.1-mini",
                    },
                    "fallback_policy": {"on_runtime_auth_error": "fallback"},
                }
            },
        },
    )

    loaded = load_config(tmp_path)
    assert loaded.llm_defaults.default == "deepseek"
    assert loaded.llm_defaults.fallbacks == ["openai"]
    assert loaded.llm_defaults.tool_loop_model == "deepseek-chat"
    assert loaded.llm_defaults.tool_loop_model_overrides == {
        "deepseek-reasoner": "deepseek-chat"
    }
    assert loaded.llm_defaults.fallback_policy is not None
    assert loaded.llm_defaults.fallback_policy.on_timeout == "fallback"
    assert loaded.agent_llm_overrides["crypto"].default == "azure_foundry"
    assert loaded.agent_llm_overrides["crypto"].fallbacks == []
    assert loaded.agent_llm_overrides["crypto"].tool_loop_model == "gpt-4.1-mini"
    assert loaded.agent_llm_overrides["crypto"].tool_loop_model_overrides == {
        "gpt-5-mini": "gpt-4.1-mini"
    }
    assert loaded.agent_llm_overrides["crypto"].fallback_policy is not None
    assert (
        loaded.agent_llm_overrides["crypto"].fallback_policy.on_runtime_auth_error
        == "fallback"
    )


def test_load_config_parses_provider_group_models_into_dotted_profile_ids(
    tmp_path: Path,
):
    _write_config(
        tmp_path / "config.json",
        {
            "llm_profiles": {
                "deepseek": {
                    "provider_id": "deepseek",
                    "driver": "openai_compatible",
                    "base_url": "https://api.deepseek.com",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "default_headers": {},
                    "timeout_seconds": 60,
                    "models": {
                        "chat": "deepseek-chat",
                        "reasoner": "deepseek-reasoner",
                    },
                }
            },
            "llm_defaults": {
                "default": "deepseek.chat",
                "fallbacks": ["deepseek.reasoner"],
            },
        },
    )

    loaded = load_config(tmp_path)
    assert "deepseek.chat" in loaded.llm_profiles
    assert "deepseek.reasoner" in loaded.llm_profiles
    assert loaded.llm_profiles["deepseek.chat"].model == "deepseek-chat"
    assert loaded.llm_profiles["deepseek.reasoner"].model == "deepseek-reasoner"
    assert loaded.llm_defaults.default == "deepseek.chat"
    assert loaded.llm_defaults.fallbacks == ["deepseek.reasoner"]


def test_route_precedence_prefers_workspace_and_empty_fallbacks_disable_inheritance(
    tmp_path: Path,
):
    _write_config(
        tmp_path / "config.json",
        {
            "llm_defaults": {
                "default": "deepseek",
                "fallbacks": ["openai", "azure_foundry"],
                "tool_loop_model": "deepseek-chat",
                "tool_loop_model_overrides": {
                    "deepseek-reasoner": "deepseek-chat",
                },
            },
            "agent_llm_overrides": {
                "crypto": {
                    "default": "azure_foundry",
                    "fallbacks": ["openai"],
                    "tool_loop_model": "gpt-4.1-mini",
                    "tool_loop_model_overrides": {"gpt-5-mini": "gpt-4.1-mini"},
                }
            },
        },
    )
    _write_config(
        tmp_path / "workspaces" / "crypto" / "config.json",
        {
            "llm": {
                "default": "openai",
                "fallbacks": [],
                "tool_loop_model": "gpt-4o-mini",
                "tool_loop_model_overrides": {"gpt-4.1": "gpt-4o-mini"},
            }
        },
    )

    loaded = load_config(tmp_path)
    runtime = load_effective_runtime_config(
        tmp_path / "config.json",
        tmp_path / "workspaces" / "crypto" / "config.json",
    )
    route = resolve_agent_llm_route(
        agent_id="crypto",
        runtime=runtime,
        config=loaded,
    )

    assert route.valid is True
    assert route.default_profile == "openai"
    assert route.fallback_profiles == ()
    assert route.tool_loop_model == "gpt-4o-mini"
    assert route.tool_loop_model_overrides == {"gpt-4.1": "gpt-4o-mini"}


def test_load_config_ignores_llm_profiles_json_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(
        "LLM_PROFILES_JSON",
        json.dumps(
            {
                "rogue": {
                    "provider_id": "rogue",
                    "driver": "openai_compatible",
                    "base_url": "https://example.invalid",
                    "model": "rogue-model",
                    "api_key_env": "ROGUE_API_KEY",
                }
            }
        ),
    )
    _write_config(tmp_path / "config.json", {})

    loaded = load_config(tmp_path)
    assert "rogue" not in loaded.llm_profiles


def test_infer_provider_prefers_explicit_provider():
    provider = infer_provider(
        "gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        explicit_provider="azure_foundry",
    )
    assert provider == "azure_foundry"
