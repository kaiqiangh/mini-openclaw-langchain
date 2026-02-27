from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

try:
    from duckduckgo_search import DDGS
except ModuleNotFoundError:  # pragma: no cover - dependency is optional in scaffold stage
    DDGS = None

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - dependency is optional in scaffold stage
    BeautifulSoup = None

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel


def _domain_match(hostname: str, domain: str) -> bool:
    host = hostname.lower().strip().lstrip(".")
    target = domain.lower().strip().lstrip(".")
    if not target:
        return False
    return host == target or host.endswith(f".{target}")


def _normalize_domains(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).lower().strip().lstrip(".") for item in value if str(item).strip()}
    return set()


def _fallback_web_search(query: str, timeout_seconds: int) -> list[dict[str, str]]:
    encoded = quote_plus(query)
    request = Request(
        f"https://duckduckgo.com/html/?q={encoded}",
        headers={"User-Agent": "mini-openclaw/0.1"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        html = response.read().decode("utf-8", errors="replace")

    if BeautifulSoup is None:
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if link is None:
            continue
        url = str(link.get("href", "")).strip()
        title = link.get_text(" ", strip=True)
        snippet_node = result.select_one(".result__snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        if not url:
            continue
        rows.append({"title": title, "href": url, "body": snippet})
    return rows


@dataclass
class WebSearchTool:
    timeout_seconds: int = 15
    default_limit: int = 5
    max_limit: int = 10

    name: str = "web_search"
    description: str = "Search the web and return compact result snippets"
    permission_level: PermissionLevel = PermissionLevel.L2_NETWORK

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'query' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        raw_limit = args.get("limit", args.get("count", self.default_limit))
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="limit must be an integer",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        limit = max(1, min(limit, self.max_limit))

        allowed_domains = _normalize_domains(args.get("allowed_domains"))
        blocked_domains = _normalize_domains(args.get("blocked_domains"))

        results: list[dict[str, Any]] = []
        try:
            raw_rows: list[dict[str, Any]]
            if DDGS is not None:
                with DDGS(timeout=self.timeout_seconds) as ddgs:
                    raw_rows = [row for row in ddgs.text(query, max_results=self.max_limit * 5) if isinstance(row, dict)]
            else:
                raw_rows = _fallback_web_search(query, self.timeout_seconds)

            for row in raw_rows:
                url = str(row.get("href", row.get("url", ""))).strip()
                title = str(row.get("title", "")).strip()
                snippet = str(row.get("body", row.get("snippet", ""))).strip()
                if not url:
                    continue

                hostname = (urlparse(url).hostname or "").lower()
                if allowed_domains and not any(_domain_match(hostname, d) for d in allowed_domains):
                    continue
                if blocked_domains and any(_domain_match(hostname, d) for d in blocked_domains):
                    continue

                results.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "source": "duckduckgo",
                    }
                )
                if len(results) >= limit:
                    break
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                tool_name=self.name,
                code="E_HTTP",
                message="Web search failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=True,
                details={"exception": str(exc)},
            )

        return ToolResult.success(
            tool_name=self.name,
            data={"query": query, "results": results},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
