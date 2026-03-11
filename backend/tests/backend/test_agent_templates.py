from __future__ import annotations

import json
from pathlib import Path

from config import runtime_from_payload, runtime_to_payload


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "agent_templates"


def _load_template(name: str) -> dict[str, object]:
    path = TEMPLATE_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_shipped_templates_match_expected_catalog():
    template_names = sorted(path.stem for path in TEMPLATE_DIR.glob("*.json"))
    assert template_names == [
        "balanced",
        "research",
        "safe-local",
        "scheduler-worker",
        "terminal-flex",
        "terminal-safe",
        "terminal-sandbox",
    ]


def test_shipped_templates_are_valid_runtime_patches():
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload.get("description"), str)
        assert payload["description"].strip()
        runtime_payload = payload.get("runtime_config")
        assert isinstance(runtime_payload, dict)

        normalized = runtime_to_payload(runtime_from_payload(runtime_payload))

        assert isinstance(normalized, dict)
        assert normalized


def test_templates_api_lists_checked_in_catalog(client, api_app):
    template_dir = api_app["base_dir"] / "agent_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    expected_names: list[str] = []

    for source_path in sorted(TEMPLATE_DIR.glob("*.json")):
        destination_path = template_dir / source_path.name
        destination_path.write_text(
            source_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        expected_names.append(source_path.stem)

    response = client.get("/api/v1/agents/templates")
    assert response.status_code == 200

    actual_names = [item["name"] for item in response.json()["data"]]
    assert actual_names == expected_names


def test_safe_local_template_explicitly_blocks_high_risk_chat_tools():
    payload = _load_template("safe-local")
    runtime_payload = payload["runtime_config"]
    assert isinstance(runtime_payload, dict)

    blocked_tools = runtime_payload.get("chat_blocked_tools")
    assert blocked_tools is not None
    assert set(blocked_tools) == {
        "fetch_url",
        "web_search",
        "terminal",
        "python_repl",
        "apply_patch",
    }


def test_scheduler_worker_template_enables_heartbeat_tooling():
    payload = _load_template("scheduler-worker")
    runtime_payload = payload["runtime_config"]
    assert isinstance(runtime_payload, dict)

    autonomous_tools = runtime_payload.get("autonomous_tools")
    assert isinstance(autonomous_tools, dict)
    heartbeat_tools = autonomous_tools.get("heartbeat_enabled_tools")
    assert heartbeat_tools == [
        "read_files",
        "read_pdf",
        "search_knowledge_base",
        "sessions_list",
        "session_history",
        "scheduler_cron_jobs",
        "scheduler_cron_runs",
        "scheduler_heartbeat_status",
        "scheduler_heartbeat_runs",
    ]


def test_terminal_safe_template_exposes_allowlisted_terminal_runtime():
    payload = _load_template("terminal-safe")
    runtime_payload = payload["runtime_config"]
    assert isinstance(runtime_payload, dict)

    terminal_payload = runtime_payload["tool_execution"]["terminal"]
    assert terminal_payload["command_policy_mode"] == "allowlist"
    assert terminal_payload["require_sandbox"] is True
    assert terminal_payload["allow_network"] is False
    assert terminal_payload["allow_shell_syntax"] is False
    assert "rg" in terminal_payload["allowed_command_prefixes"]


def test_terminal_sandbox_template_uses_denylist_with_required_sandbox():
    payload = _load_template("terminal-sandbox")
    runtime_payload = payload["runtime_config"]
    assert isinstance(runtime_payload, dict)

    terminal_payload = runtime_payload["tool_execution"]["terminal"]
    assert terminal_payload["command_policy_mode"] == "denylist"
    assert terminal_payload["require_sandbox"] is True
    assert terminal_payload["allowed_command_prefixes"] == []
    assert terminal_payload["denied_command_prefixes"]


def test_terminal_flex_template_uses_unsandboxed_denylist_profile():
    payload = _load_template("terminal-flex")
    runtime_payload = payload["runtime_config"]
    assert isinstance(runtime_payload, dict)

    terminal_payload = runtime_payload["tool_execution"]["terminal"]
    assert terminal_payload["command_policy_mode"] == "denylist"
    assert terminal_payload["require_sandbox"] is False
    assert terminal_payload["allowed_command_prefixes"] == []
    assert terminal_payload["denied_command_prefixes"]
