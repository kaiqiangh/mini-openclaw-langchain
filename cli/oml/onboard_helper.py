#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import (  # noqa: E402
    load_config,
    load_runtime_config,
    runtime_from_payload,
    runtime_to_payload,
    save_runtime_config_to_path,
)

DEFAULT_TOOL_NAMES: tuple[str, ...] = (
    "agents_list",
    "apply_patch",
    "fetch_url",
    "python_repl",
    "read_files",
    "read_pdf",
    "scheduler_cron_jobs",
    "scheduler_cron_runs",
    "scheduler_heartbeat_runs",
    "scheduler_heartbeat_status",
    "search_knowledge_base",
    "session_history",
    "sessions_list",
    "terminal",
    "web_search",
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _normalize_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if not item or item in normalized:
            continue
        normalized.append(item)
    return normalized


def _parse_csv(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return _normalize_list(raw.split(","))


def _print_key_value(key: str, value: Any) -> None:
    if isinstance(value, list):
        rendered = ",".join(str(item) for item in value)
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value)
    print(f"{key}={rendered}")


def _root_runtime_payload(base_dir: Path) -> tuple[dict[str, Any], Any]:
    app_config = load_config(base_dir)
    payload = runtime_to_payload(app_config.runtime)
    llm_payload: dict[str, Any] = {}
    default_profile = str(app_config.llm_defaults.default or "").strip()
    if default_profile:
        llm_payload["default"] = default_profile
    if app_config.llm_defaults.fallbacks is not None:
        llm_payload["fallbacks"] = _normalize_list(app_config.llm_defaults.fallbacks)
    if llm_payload:
        payload["llm"] = llm_payload
    return payload, app_config


def _list_llm_routes(base_dir: Path) -> list[str]:
    _, app_config = _root_runtime_payload(base_dir)
    return sorted(str(name).strip() for name in app_config.llm_profiles.keys() if str(name).strip())


def _load_template_patch(base_dir: Path, template_name: str) -> dict[str, Any]:
    normalized = template_name.strip()
    if not normalized or normalized == "none":
        return {}
    path = base_dir / "agent_templates" / f"{normalized}.json"
    if not path.exists() or not path.is_file():
        raise ValueError(f"Unknown template: {normalized}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Template {normalized} has invalid payload shape")
    runtime_payload = payload.get("runtime_config", payload)
    if not isinstance(runtime_payload, dict):
        raise ValueError(f"Template {normalized} runtime config must be an object")
    runtime_from_payload(runtime_payload)
    return runtime_payload


def _list_templates(base_dir: Path) -> list[str]:
    template_dir = base_dir / "agent_templates"
    if not template_dir.exists():
        return []
    templates: list[str] = []
    for path in sorted(template_dir.glob("*.json"), key=lambda item: item.name):
        name = path.stem.strip()
        if not name:
            continue
        try:
            _load_template_patch(base_dir, name)
        except Exception:
            continue
        templates.append(name)
    return templates


def _tool_names(base_dir: Path) -> list[str]:
    try:
        from tools import get_all_declared_tools  # noqa: WPS433

        runtime = load_runtime_config(base_dir / "config.json")
        root_dir = base_dir / "workspaces" / "default"
        tools = get_all_declared_tools(root_dir, runtime, config_base_dir=base_dir)
        names = sorted({tool.name for tool in tools if str(tool.name).strip()})
        if names:
            return names
    except Exception:
        pass
    return list(DEFAULT_TOOL_NAMES)


def _validate_llm_routes(
    *,
    valid_routes: set[str],
    default_route: str | None,
    fallback_routes: list[str] | None,
) -> None:
    if default_route:
        if default_route not in valid_routes:
            raise ValueError(f"Unknown LLM route: {default_route}")
    if fallback_routes is None:
        return
    seen: set[str] = set()
    for route in fallback_routes:
        if route not in valid_routes:
            raise ValueError(f"Unknown LLM route: {route}")
        if route == default_route:
            raise ValueError(f"Fallback route duplicates the default: {route}")
        if route in seen:
            raise ValueError(f"Duplicate fallback route: {route}")
        seen.add(route)


def _validate_tools(valid_tools: set[str], values: list[str], flag_name: str) -> list[str]:
    normalized = _normalize_list(values)
    unknown = [name for name in normalized if name not in valid_tools]
    if unknown:
        raise ValueError(f"Unknown tool name(s) for {flag_name}: {', '.join(unknown)}")
    return normalized


def _agent_root(base_dir: Path, agent_id: str) -> Path:
    return base_dir / "workspaces" / agent_id


def _agent_config_path(base_dir: Path, agent_id: str) -> Path:
    return _agent_root(base_dir, agent_id) / "config.json"


def _build_base_payload(
    *,
    base_dir: Path,
    agent_id: str,
    template_name: str,
    mode: str,
) -> dict[str, Any]:
    payload, _ = _root_runtime_payload(base_dir)
    template_patch = _load_template_patch(base_dir, template_name)
    if template_patch:
        payload = _deep_merge(payload, template_patch)
    if mode == "edit":
        config_path = _agent_config_path(base_dir, agent_id)
        if not config_path.exists():
            raise ValueError(f"Agent does not exist: {agent_id}")
        existing_payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(existing_payload, dict):
            raise ValueError(f"Agent config is invalid: {config_path}")
        payload = _deep_merge(payload, existing_payload)
    return runtime_to_payload(runtime_from_payload(payload))


def _apply_tool_preset(
    payload: dict[str, Any],
    *,
    preset: str,
    explicit_policy_mode: str | None,
) -> None:
    if preset == "balanced":
        return
    chat_enabled = _normalize_list(list(payload.get("chat_enabled_tools", [])))
    chat_blocked = _normalize_list(list(payload.get("chat_blocked_tools", [])))
    autonomous = payload.setdefault("autonomous_tools", {})
    heartbeat_tools = _normalize_list(list(autonomous.get("heartbeat_enabled_tools", [])))
    cron_tools = _normalize_list(list(autonomous.get("cron_enabled_tools", [])))
    terminal_cfg = payload.setdefault("tool_execution", {}).setdefault("terminal", {})

    if preset == "safe":
        chat_enabled = [name for name in chat_enabled if name not in {"terminal", "apply_patch"}]
        cron_tools = [name for name in cron_tools if name not in {"terminal", "apply_patch"}]
        if "python_repl" not in chat_blocked:
            chat_blocked.append("python_repl")
    elif preset == "builder":
        for name in ("terminal", "apply_patch"):
            if name not in chat_enabled:
                chat_enabled.append(name)
        if "terminal" not in cron_tools:
            cron_tools.append("terminal")
        if "python_repl" not in chat_blocked:
            chat_blocked.append("python_repl")
        if explicit_policy_mode is None:
            terminal_cfg["command_policy_mode"] = "denylist"
    else:
        raise ValueError(f"Unknown tool preset: {preset}")

    payload["chat_enabled_tools"] = chat_enabled
    payload["chat_blocked_tools"] = chat_blocked
    autonomous["heartbeat_enabled_tools"] = heartbeat_tools
    autonomous["cron_enabled_tools"] = cron_tools


def _build_apply_payload(args: argparse.Namespace, base_dir: Path) -> tuple[dict[str, Any], bool]:
    payload = _build_base_payload(
        base_dir=base_dir,
        agent_id=args.agent,
        template_name=args.template,
        mode=args.mode,
    )
    config_path = _agent_config_path(base_dir, args.agent)
    created = not _agent_root(base_dir, args.agent).exists()
    valid_routes = set(_list_llm_routes(base_dir))
    valid_tools = set(_tool_names(base_dir))

    if args.llm_default is not None:
        default_route = args.llm_default.strip()
        _validate_llm_routes(
            valid_routes=valid_routes,
            default_route=default_route,
            fallback_routes=None,
        )
        payload.setdefault("llm", {})["default"] = default_route

    current_default = str(payload.get("llm", {}).get("default", "")).strip() or None

    if args.clear_fallbacks:
        payload.setdefault("llm", {})["fallbacks"] = []
    elif args.fallbacks is not None:
        fallbacks = _normalize_list(args.fallbacks)
        _validate_llm_routes(
            valid_routes=valid_routes,
            default_route=current_default,
            fallback_routes=fallbacks,
        )
        payload.setdefault("llm", {})["fallbacks"] = fallbacks

    if args.rag_mode is not None:
        payload["rag_mode"] = args.rag_mode

    _apply_tool_preset(
        payload,
        preset=args.tool_preset,
        explicit_policy_mode=args.terminal_policy_mode,
    )

    if args.chat_tools_mode == "replace":
        payload["chat_enabled_tools"] = _validate_tools(
            valid_tools,
            args.chat_tools,
            "--chat-tools",
        )
    elif args.chat_tools_mode == "clear":
        payload["chat_enabled_tools"] = []

    if args.heartbeat_tools_mode == "replace":
        payload.setdefault("autonomous_tools", {})["heartbeat_enabled_tools"] = _validate_tools(
            valid_tools,
            args.heartbeat_tools,
            "--heartbeat-tools",
        )
    elif args.heartbeat_tools_mode == "clear":
        payload.setdefault("autonomous_tools", {})["heartbeat_enabled_tools"] = []

    if args.cron_tools_mode == "replace":
        payload.setdefault("autonomous_tools", {})["cron_enabled_tools"] = _validate_tools(
            valid_tools,
            args.cron_tools,
            "--cron-tools",
        )
    elif args.cron_tools_mode == "clear":
        payload.setdefault("autonomous_tools", {})["cron_enabled_tools"] = []

    if args.max_steps is not None:
        payload.setdefault("agent_runtime", {})["max_steps"] = args.max_steps
    if args.timeout_seconds is not None:
        payload.setdefault("llm_runtime", {})["timeout_seconds"] = args.timeout_seconds
    if args.heartbeat is not None:
        payload.setdefault("heartbeat", {})["enabled"] = args.heartbeat
    if args.cron is not None:
        payload.setdefault("cron", {})["enabled"] = args.cron
    if args.terminal_sandbox_mode is not None:
        payload.setdefault("tool_execution", {}).setdefault("terminal", {})[
            "sandbox_mode"
        ] = args.terminal_sandbox_mode
    if args.terminal_policy_mode is not None:
        payload.setdefault("tool_execution", {}).setdefault("terminal", {})[
            "command_policy_mode"
        ] = args.terminal_policy_mode

    final_runtime = runtime_from_payload(payload)
    final_payload = runtime_to_payload(final_runtime)

    final_default = str(final_payload.get("llm", {}).get("default", "")).strip() or None
    final_fallbacks = _normalize_list(list(final_payload.get("llm", {}).get("fallbacks", [])))
    _validate_llm_routes(
        valid_routes=valid_routes,
        default_route=final_default,
        fallback_routes=final_fallbacks,
    )

    save_runtime_config_to_path(config_path, final_runtime)
    return final_payload, created


def _command_list_templates(args: argparse.Namespace) -> int:
    _ = args
    for name in _list_templates(REPO_ROOT / "backend"):
        print(name)
    return 0


def _command_list_llm_routes(args: argparse.Namespace) -> int:
    _ = args
    for name in _list_llm_routes(REPO_ROOT / "backend"):
        print(name)
    return 0


def _command_list_tools(args: argparse.Namespace) -> int:
    _ = args
    for name in _tool_names(REPO_ROOT / "backend"):
        print(name)
    return 0


def _command_prompt_defaults(args: argparse.Namespace) -> int:
    base_dir = REPO_ROOT / "backend"
    payload = _build_base_payload(
        base_dir=base_dir,
        agent_id=args.agent,
        template_name=args.template,
        mode=args.mode,
    )
    llm_payload = payload.get("llm", {})
    _print_key_value("llm_default", llm_payload.get("default", ""))
    _print_key_value("llm_fallbacks", _normalize_list(list(llm_payload.get("fallbacks", []))))
    _print_key_value("rag_mode", bool(payload.get("rag_mode", False)))
    _print_key_value("chat_tools", _normalize_list(list(payload.get("chat_enabled_tools", []))))
    _print_key_value(
        "heartbeat_tools",
        _normalize_list(
            list(payload.get("autonomous_tools", {}).get("heartbeat_enabled_tools", []))
        ),
    )
    _print_key_value(
        "cron_tools",
        _normalize_list(
            list(payload.get("autonomous_tools", {}).get("cron_enabled_tools", []))
        ),
    )
    _print_key_value("max_steps", payload.get("agent_runtime", {}).get("max_steps", ""))
    _print_key_value(
        "timeout_seconds",
        payload.get("llm_runtime", {}).get("timeout_seconds", ""),
    )
    _print_key_value(
        "heartbeat_enabled",
        bool(payload.get("heartbeat", {}).get("enabled", False)),
    )
    _print_key_value("cron_enabled", bool(payload.get("cron", {}).get("enabled", False)))
    _print_key_value(
        "terminal_sandbox_mode",
        payload.get("tool_execution", {}).get("terminal", {}).get("sandbox_mode", ""),
    )
    _print_key_value(
        "terminal_policy_mode",
        payload.get("tool_execution", {}).get("terminal", {}).get("command_policy_mode", ""),
    )
    return 0


def _command_apply(args: argparse.Namespace) -> int:
    base_dir = REPO_ROOT / "backend"
    final_payload, created = _build_apply_payload(args, base_dir)
    config_path = _agent_config_path(base_dir, args.agent)
    llm_payload = final_payload.get("llm", {})
    _print_key_value("agent_id", args.agent)
    _print_key_value("config_path", str(config_path))
    _print_key_value("created", created)
    _print_key_value("mode", args.mode)
    _print_key_value("template", args.template)
    _print_key_value("llm_default", llm_payload.get("default", ""))
    _print_key_value("llm_fallbacks", _normalize_list(list(llm_payload.get("fallbacks", []))))
    _print_key_value("rag_mode", bool(final_payload.get("rag_mode", False)))
    return 0


def _parse_toggle(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {raw}")


def _parse_on_off(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    raise argparse.ArgumentTypeError(f"expected on|off, got: {raw}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onboard_helper.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-templates")
    subparsers.add_parser("list-llm-routes")
    subparsers.add_parser("list-tools")

    prompt_defaults = subparsers.add_parser("prompt-defaults")
    prompt_defaults.add_argument("--agent", required=True)
    prompt_defaults.add_argument("--template", default="none")
    prompt_defaults.add_argument(
        "--mode",
        choices=("create", "edit", "reset"),
        required=True,
    )

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--agent", required=True)
    apply_parser.add_argument("--template", default="none")
    apply_parser.add_argument(
        "--mode",
        choices=("create", "edit", "reset"),
        required=True,
    )
    apply_parser.add_argument("--llm-default")
    apply_parser.add_argument("--fallbacks")
    apply_parser.add_argument("--clear-fallbacks", action="store_true")
    apply_parser.add_argument(
        "--rag-mode",
        type=_parse_toggle,
    )
    apply_parser.add_argument(
        "--tool-preset",
        choices=("safe", "balanced", "builder"),
        default="balanced",
    )
    apply_parser.add_argument("--chat-tools")
    apply_parser.add_argument(
        "--chat-tools-mode",
        choices=("inherit", "replace", "clear"),
        default="inherit",
    )
    apply_parser.add_argument("--heartbeat-tools")
    apply_parser.add_argument(
        "--heartbeat-tools-mode",
        choices=("inherit", "replace", "clear"),
        default="inherit",
    )
    apply_parser.add_argument("--cron-tools")
    apply_parser.add_argument(
        "--cron-tools-mode",
        choices=("inherit", "replace", "clear"),
        default="inherit",
    )
    apply_parser.add_argument("--max-steps", type=int)
    apply_parser.add_argument("--timeout-seconds", type=int)
    apply_parser.add_argument("--terminal-sandbox-mode")
    apply_parser.add_argument("--terminal-policy-mode")
    apply_parser.add_argument("--heartbeat", type=_parse_on_off)
    apply_parser.add_argument("--cron", type=_parse_on_off)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "fallbacks", None) is not None:
        if args.fallbacks.strip().lower() == "none":
            args.clear_fallbacks = True
            args.fallbacks = []
        else:
            args.fallbacks = _parse_csv(args.fallbacks)
    if getattr(args, "chat_tools", None) is not None:
        if args.chat_tools.strip().lower() == "none":
            args.chat_tools_mode = "clear"
            args.chat_tools = []
        else:
            args.chat_tools_mode = "replace"
            args.chat_tools = _parse_csv(args.chat_tools)
    else:
        args.chat_tools = []
    if getattr(args, "heartbeat_tools", None) is not None:
        if args.heartbeat_tools.strip().lower() == "none":
            args.heartbeat_tools_mode = "clear"
            args.heartbeat_tools = []
        else:
            args.heartbeat_tools_mode = "replace"
            args.heartbeat_tools = _parse_csv(args.heartbeat_tools)
    else:
        args.heartbeat_tools = []
    if getattr(args, "cron_tools", None) is not None:
        if args.cron_tools.strip().lower() == "none":
            args.cron_tools_mode = "clear"
            args.cron_tools = []
        else:
            args.cron_tools_mode = "replace"
            args.cron_tools = _parse_csv(args.cron_tools)
    else:
        args.cron_tools = []

    try:
        if args.command == "list-templates":
            return _command_list_templates(args)
        if args.command == "list-llm-routes":
            return _command_list_llm_routes(args)
        if args.command == "list-tools":
            return _command_list_tools(args)
        if args.command == "prompt-defaults":
            return _command_prompt_defaults(args)
        if args.command == "apply":
            return _command_apply(args)
        parser.error(f"Unknown command: {args.command}")
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
