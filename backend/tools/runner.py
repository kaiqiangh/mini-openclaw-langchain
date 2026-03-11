from __future__ import annotations

import json
import time
from typing import Any
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from storage.run_store import AuditStore
from .base import MiniTool, ToolContext
from .contracts import ToolResult
from .policy import ToolPolicyEngine
from utils.redaction import redact_json_line

_SEARCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "binance",
    "chain",
    "for",
    "in",
    "is",
    "latest",
    "march",
    "of",
    "on",
    "popular",
    "smart",
    "the",
    "today",
    "token",
    "tokens",
    "trending",
    "which",
}


class ToolRunner:
    def __init__(
        self,
        policy_engine: ToolPolicyEngine,
        audit_file: Path | None = None,
        audit_store: AuditStore | None = None,
        repeat_identical_failure_limit: int = 2,
    ) -> None:
        self.policy_engine = policy_engine
        self.audit_file = audit_file
        self.audit_store = audit_store
        self.repeat_identical_failure_limit = max(
            1, int(repeat_identical_failure_limit)
        )
        self._repeat_failure_counts: dict[tuple[str, str, str], int] = {}
        self._recent_search_terms: dict[tuple[str, str], list[frozenset[str]]] = {}
        self._recent_fetch_urls: dict[tuple[str, str], set[str]] = {}

    @staticmethod
    def _args_fingerprint(args: dict[str, Any]) -> str:
        try:
            return json.dumps(args, sort_keys=True, ensure_ascii=True, default=str)
        except Exception:
            return str(args)

    @staticmethod
    def _scope_key(context: ToolContext) -> str:
        if context.run_id:
            return context.run_id
        return f"{context.session_id or '__session__'}:{context.trigger_type}"

    @staticmethod
    def _normalize_search_terms(query: str) -> frozenset[str]:
        tokens: set[str] = set()
        normalized = query.lower().replace("binance smart chain", "bsc")
        for raw in normalized.replace('"', " ").replace("'", " ").split():
            token = raw.strip(".,:;!?()[]{}<>/\\|`~!@#$%^&*+-=_")
            if token.endswith("s") and len(token) > 4:
                token = token[:-1]
            if len(token) < 3 or token in _SEARCH_STOPWORDS:
                continue
            tokens.add(token)
        return frozenset(tokens)

    @staticmethod
    def _canonical_fetch_url(raw_url: str) -> str:
        parsed = urlparse(raw_url)
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.hostname or "").lower().strip(".")
        if not host:
            return raw_url.strip()
        try:
            port = parsed.port
        except ValueError:
            return raw_url.strip()
        host_token = f"[{host}]" if ":" in host and not host.startswith("[") else host
        default_port = 80 if scheme == "http" else 443 if scheme == "https" else None
        netloc = host_token
        if port is not None and port != default_port:
            netloc = f"{host_token}:{port}"
        path = parsed.path or "/"
        return urlunparse((scheme, netloc, path, "", "", ""))

    @staticmethod
    def _jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    def _search_repeat_reason(
        self, tool_name: str, args: dict[str, Any], context: ToolContext
    ) -> str | None:
        scope_key = self._scope_key(context)

        if tool_name == "web_search":
            query = str(args.get("query", "")).strip()
            if not query:
                return None
            terms = self._normalize_search_terms(query)
            if not terms:
                return None
            history_key = (scope_key, tool_name)
            prior_terms = self._recent_search_terms.get(history_key, [])
            exact_matches = sum(1 for item in prior_terms if item == terms)
            near_matches = sum(
                1
                for item in prior_terms
                if self._jaccard_similarity(item, terms) >= 0.6
            )
            if exact_matches >= 1:
                return "Repeated identical web search query; synthesize current results or use a selected skill."
            if near_matches >= 2:
                return "Repeated near-duplicate web searches in the same run; use the current results or a selected skill instead."
            return None

        if tool_name == "fetch_url":
            url = str(args.get("url", "")).strip()
            if not url:
                return None
            canonical = self._canonical_fetch_url(url)
            history_key = (scope_key, tool_name)
            prior_urls = self._recent_fetch_urls.get(history_key, set())
            if canonical in prior_urls:
                return "Repeated fetch_url request for the same page; use the existing fetched content instead."

        return None

    def _record_search_call(
        self, tool_name: str, args: dict[str, Any], context: ToolContext
    ) -> None:
        scope_key = self._scope_key(context)
        if tool_name == "web_search":
            query = str(args.get("query", "")).strip()
            if not query:
                return
            terms = self._normalize_search_terms(query)
            if not terms:
                return
            history_key = (scope_key, tool_name)
            self._recent_search_terms.setdefault(history_key, []).append(terms)
            return

        if tool_name == "fetch_url":
            url = str(args.get("url", "")).strip()
            if not url:
                return
            canonical = self._canonical_fetch_url(url)
            history_key = (scope_key, tool_name)
            self._recent_fetch_urls.setdefault(history_key, set()).add(canonical)

    def _write_audit(self, payload: dict[str, Any]) -> None:
        if self.audit_file is None:
            return
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_file.open("a", encoding="utf-8") as fh:
            fh.write(redact_json_line(payload) + "\n")

    def run_tool(
        self,
        tool: MiniTool,
        *,
        args: dict[str, Any],
        context: ToolContext,
        explicit_enabled_tools: list[str] | None = None,
        explicit_blocked_tools: list[str] | None = None,
    ) -> ToolResult:
        tool_metadata_fn = getattr(tool, "audit_metadata", None)
        tool_metadata: dict[str, Any] = {}
        if callable(tool_metadata_fn):
            try:
                candidate = tool_metadata_fn()
                if isinstance(candidate, dict):
                    tool_metadata = candidate
            except Exception:
                tool_metadata = {}

        effective_enabled_tools = explicit_enabled_tools
        if effective_enabled_tools is None and context.explicit_enabled_tools:
            effective_enabled_tools = list(context.explicit_enabled_tools)
        effective_blocked_tools = explicit_blocked_tools
        if effective_blocked_tools is None and context.explicit_blocked_tools:
            effective_blocked_tools = list(context.explicit_blocked_tools)

        started = time.monotonic()
        self._write_audit(
            {
                "event": "tool_start",
                "tool": tool.name,
                "run_id": context.run_id,
                "session_id": context.session_id,
                "trigger_type": context.trigger_type,
                "args": args,
                "tool_metadata": tool_metadata,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        decision = self.policy_engine.is_allowed(
            tool_name=tool.name,
            permission_level=tool.permission_level,
            trigger_type=context.trigger_type,
            explicit_enabled_tools=effective_enabled_tools,
            explicit_blocked_tools=effective_blocked_tools,
        )
        if not decision.allowed:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "denied",
                    "reason": decision.reason,
                    "tool_metadata": tool_metadata,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="denied",
                    duration_ms=duration_ms,
                    details={"reason": decision.reason},
                )
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_POLICY_DENIED",
                message=decision.reason,
                duration_ms=duration_ms,
                retryable=False,
            )

        repeat_reason = self._search_repeat_reason(tool.name, args, context)
        if repeat_reason is not None:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "denied",
                    "reason": repeat_reason,
                    "tool_metadata": tool_metadata,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="denied",
                    duration_ms=duration_ms,
                    details={"reason": repeat_reason},
                )
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_POLICY_DENIED",
                message=repeat_reason,
                duration_ms=duration_ms,
                retryable=False,
            )

        failure_key = (
            self._scope_key(context),
            tool.name,
            self._args_fingerprint(args),
        )
        prior_failures = self._repeat_failure_counts.get(failure_key, 0)
        if prior_failures >= self.repeat_identical_failure_limit:
            duration_ms = int((time.monotonic() - started) * 1000)
            reason = "Repeated identical tool failure; retry blocked for this run"
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "denied",
                    "reason": reason,
                    "tool_metadata": tool_metadata,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="denied",
                    duration_ms=duration_ms,
                    details={"reason": reason},
                )
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_POLICY_DENIED",
                message=reason,
                duration_ms=duration_ms,
                retryable=False,
            )

        try:
            result = tool.run(args, context)
            if result.ok:
                self._repeat_failure_counts.pop(failure_key, None)
                self._record_search_call(tool.name, args, context)
            else:
                self._repeat_failure_counts[failure_key] = prior_failures + 1
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": result.meta.duration_ms,
                    "ok": result.ok,
                    "policy_decision": "allowed",
                    "tool_metadata": tool_metadata,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="ok" if result.ok else "error",
                    duration_ms=result.meta.duration_ms,
                    details={"truncated": result.meta.truncated},
                )
            return result
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.monotonic() - started) * 1000)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "allowed",
                    "error": str(exc),
                    "tool_metadata": tool_metadata,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="error",
                    duration_ms=duration_ms,
                    details={"exception": str(exc)},
                )
            self._repeat_failure_counts[failure_key] = prior_failures + 1
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_INTERNAL",
                message="Unhandled tool exception",
                duration_ms=duration_ms,
                retryable=False,
                details={"exception": str(exc)},
            )
