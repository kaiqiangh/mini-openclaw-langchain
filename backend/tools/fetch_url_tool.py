from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import html2text
except ModuleNotFoundError:  # pragma: no cover - optional at scaffold stage
    html2text = None

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - optional at scaffold stage
    BeautifulSoup = None

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel


@dataclass
class FetchUrlTool:
    timeout_seconds: int = 15
    output_char_limit: int = 5000
    max_output_char_limit: int = 100000
    allow_hosts: tuple[str, ...] = ()

    name: str = "fetch_url"
    description: str = "Fetch remote URL and convert content to compact text"
    permission_level: PermissionLevel = PermissionLevel.L2_NETWORK

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        url = str(args.get("url", "")).strip()
        extract_mode = str(args.get("extractMode", args.get("extract_mode", "markdown"))).strip().lower() or "markdown"
        if extract_mode not in {"markdown", "text", "html"}:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="extractMode must be one of: markdown, text, html",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        max_chars_arg = args.get("maxChars", args.get("max_chars"))
        max_chars = self.output_char_limit
        if max_chars_arg is not None:
            try:
                max_chars = int(max_chars_arg)
            except (TypeError, ValueError):
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_INVALID_ARGS",
                    message="maxChars must be an integer",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            max_chars = max(256, min(max_chars, self.max_output_char_limit))

        if not url:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'url' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        parsed = urlparse(url)
        host = parsed.hostname or ""
        if self.allow_hosts and host not in self.allow_hosts:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message=f"Host '{host}' is not allowlisted",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        request = Request(url, headers={"User-Agent": "mini-openclaw/0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                content_type = (response.headers.get("Content-Type", "") or "").lower()
                status = int(getattr(response, "status", 200))
        except TimeoutError:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_TIMEOUT",
                message="Request timed out",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                tool_name=self.name,
                code="E_HTTP",
                message="Failed to fetch URL",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"exception": str(exc)},
            )

        text = ""
        try:
            decoded = raw.decode("utf-8", errors="replace")
            if "application/json" in content_type:
                parsed_json = json.loads(decoded)
                text = json.dumps(parsed_json, ensure_ascii=False, indent=2)
            elif "text/html" in content_type:
                if extract_mode == "html":
                    text = decoded
                elif extract_mode == "text" and BeautifulSoup is not None:
                    soup = BeautifulSoup(decoded, "html.parser")
                    text = soup.get_text(separator="\n", strip=True)
                elif BeautifulSoup is not None and html2text is not None:
                    soup = BeautifulSoup(decoded, "html.parser")
                    cleaned = str(soup)
                    text = html2text.html2text(cleaned)
                elif BeautifulSoup is not None:
                    soup = BeautifulSoup(decoded, "html.parser")
                    text = soup.get_text(separator="\n", strip=True)
                else:
                    text = decoded
            else:
                text = decoded
        except Exception:  # noqa: BLE001
            text = raw.decode("utf-8", errors="replace")

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "status": status,
                "url": url,
                "content": text,
                "truncated": truncated,
                "extract_mode": extract_mode,
                "max_chars": max_chars,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
