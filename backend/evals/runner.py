"""Eval harness runner — loads YAML cases and executes through real policy engine."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tools.policy import PermissionLevel, ToolPolicyEngine


EVALS_DIR = Path(__file__).resolve().parent / "cases"


@dataclass
class EvalResult:
    name: str
    tool: str
    expect: str
    actual: str
    passed: bool
    reason: str = ""
    duration_ms: int = 0


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    safety_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "safety_score": round(self.safety_score, 4),
            "failures": [
                {"name": r.name, "tool": r.tool, "expect": r.expect, "actual": r.actual, "reason": r.reason}
                for r in self.results if not r.passed
            ],
        }


_TOOL_LEVELS = {
    "terminal": PermissionLevel.L3_SYSTEM,
    "python_repl": PermissionLevel.L1_WRITE,
    "apply_patch": PermissionLevel.L1_WRITE,
    "fetch_url": PermissionLevel.L2_NETWORK,
    "read_files": PermissionLevel.L0_READ,
    "read_pdf": PermissionLevel.L0_READ,
    "search_knowledge_base": PermissionLevel.L0_READ,
    "web_search": PermissionLevel.L2_NETWORK,
    "sessions_list": PermissionLevel.L0_READ,
    "session_history": PermissionLevel.L0_READ,
    "agents_list": PermissionLevel.L0_READ,
}


def load_cases(cases_dir: Path = EVALS_DIR) -> list[dict[str, Any]]:
    all_cases: list[dict[str, Any]] = []
    for yaml_file in sorted(cases_dir.glob("*.yaml")):
        with yaml_file.open("r") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "cases" in data:
            for case in data["cases"]:
                case["_source"] = yaml_file.name
                all_cases.append(case)
    return all_cases


def run_evals(cases_dir: Path = EVALS_DIR) -> EvalReport:
    engine = ToolPolicyEngine()
    cases = load_cases(cases_dir)
    report = EvalReport()

    for case in cases:
        name = case.get("name", "unnamed")
        tool = case.get("tool", "")
        trigger = case.get("trigger_type", "chat")
        expect = case.get("expect", "allowed")
        explicit_enabled = case.get("explicit_enabled")
        explicit_blocked = case.get("explicit_blocked")
        reason_contains = case.get("reason_contains", "")

        level = _TOOL_LEVELS.get(tool, PermissionLevel.L0_READ)
        started = time.monotonic()

        decision = engine.is_allowed(
            tool_name=tool,
            permission_level=level,
            trigger_type=trigger,
            explicit_enabled_tools=explicit_enabled,
            explicit_blocked_tools=explicit_blocked,
        )

        duration_ms = int((time.monotonic() - started) * 1000)
        actual = "allowed" if decision.allowed else "blocked"
        passed = actual == expect
        reason_ok = True
        if reason_contains and actual == "blocked":
            reason_ok = reason_contains.lower() in decision.reason.lower()

        result = EvalResult(
            name=name,
            tool=tool,
            expect=expect,
            actual=actual,
            passed=passed and reason_ok,
            reason=decision.reason,
            duration_ms=duration_ms,
        )
        report.results.append(result)

    report.total = len(report.results)
    report.passed = sum(1 for r in report.results if r.passed)
    report.failed = report.total - report.passed
    report.safety_score = report.passed / report.total if report.total > 0 else 0.0
    return report


def main() -> None:
    report = run_evals()
    print(json.dumps(report.to_dict(), indent=2))
    if report.failed > 0:
        print(f"\n\033[91m❌ {report.failed}/{report.total} evals failed\033[0m", file=sys.stderr)
        sys.exit(1)
    print(f"\n\033[92m✅ All {report.total} evals passed (safety score: {report.safety_score:.2%})\033[0m")


if __name__ == "__main__":
    main()
