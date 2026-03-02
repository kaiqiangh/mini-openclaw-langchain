from __future__ import annotations

import json
from pathlib import Path

from config import load_config, validate_required_secrets
from usage.pricing import infer_provider


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")


def test_validate_required_secrets_only_checks_active_profile(monkeypatch, tmp_path: Path):
    _write_config(
        tmp_path / "config.json",
        {
            "default_llm_profile": "openai",
            "llm_runtime": {"profile": ""},
        },
    )
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    loaded = load_config(tmp_path)
    missing = validate_required_secrets(loaded)
    assert "APP_ADMIN_TOKEN" in missing
    assert "OPENAI_API_KEY" in missing
    assert "DEEPSEEK_API_KEY" not in missing

    monkeypatch.setenv("APP_ADMIN_TOKEN", "token-1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    loaded = load_config(tmp_path)
    assert validate_required_secrets(loaded) == []


def test_azure_profile_requires_model_base_url_and_key(monkeypatch, tmp_path: Path):
    _write_config(
        tmp_path / "config.json",
        {
            "default_llm_profile": "azure_foundry",
            "llm_runtime": {"profile": "azure_foundry"},
        },
    )
    monkeypatch.setenv("APP_ADMIN_TOKEN", "token-1")
    monkeypatch.delenv("AZURE_FOUNDRY_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_FOUNDRY_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_FOUNDRY_MODEL", raising=False)

    loaded = load_config(tmp_path)
    missing = validate_required_secrets(loaded)
    assert "AZURE_FOUNDRY_API_KEY" in missing
    assert "LLM_PROFILE_AZURE_FOUNDRY_BASE_URL" in missing
    assert "LLM_PROFILE_AZURE_FOUNDRY_MODEL" in missing

    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "key-1")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://example.foundry.azure.com/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "gpt-4.1-mini")
    loaded = load_config(tmp_path)
    assert validate_required_secrets(loaded) == []


def test_infer_provider_prefers_explicit_provider():
    provider = infer_provider(
        "gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        explicit_provider="azure_foundry",
    )
    assert provider == "azure_foundry"

