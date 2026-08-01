from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

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


class _UrlPolicyError(ValueError):
    pass


class _PinnedConnectionMixin:
    def _connect_to_validated_host(self) -> None:
        addresses = self._resolve_host(self.host)
        last_error: OSError | None = None
        for address in addresses:
            try:
                self.sock = self._create_connection(
                    (address, self.port), self.timeout, self.source_address
                )
                break
            except OSError as exc:
                last_error = exc

        if self.sock is None:
            raise last_error or OSError(f"Unable to connect to {self.host}")

        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        *,
        resolver: Callable[[str], tuple[str, ...]],
        **kwargs: Any,
    ) -> None:
        self._resolve_host = resolver
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self._connect_to_validated_host()


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        *,
        resolver: Callable[[str], tuple[str, ...]],
        **kwargs: Any,
    ) -> None:
        self._resolve_host = resolver
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self._connect_to_validated_host()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=server_hostname
        )


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, resolver: Callable[[str], tuple[str, ...]]) -> None:
        super().__init__()
        self._resolve_host = resolver

    def http_open(self, request):  # type: ignore[no-untyped-def]
        return self.do_open(
            _PinnedHTTPConnection, request, resolver=self._resolve_host
        )


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, resolver: Callable[[str], tuple[str, ...]]) -> None:
        super().__init__()
        self._resolve_host = resolver

    def https_open(self, request):  # type: ignore[no-untyped-def]
        return self.do_open(
            _PinnedHTTPSConnection,
            request,
            context=self._context,
            resolver=self._resolve_host,
        )


@dataclass
class FetchUrlTool:
    timeout_seconds: int = 15
    output_char_limit: int = 5000
    max_output_char_limit: int = 100000
    allowed_schemes: tuple[str, ...] = ("http", "https")
    allow_hosts: tuple[str, ...] = ()
    block_private_networks: bool = True
    max_redirects: int = 3
    max_content_bytes: int = 2_000_000

    name: str = "fetch_url"
    description: str = "Fetch remote URL and convert content to compact text"
    permission_level: PermissionLevel = PermissionLevel.L2_NETWORK

    @staticmethod
    def _is_blocked_ip(value: str) -> bool:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return False
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )

    @staticmethod
    def _normalize_host(host: str) -> str:
        return host.strip().lower().strip("[]").rstrip(".")

    @classmethod
    def _resolve_host_addresses(cls, host: str) -> tuple[str, ...]:
        normalized = cls._normalize_host(host)
        try:
            return (str(ipaddress.ip_address(normalized)),)
        except ValueError:
            pass

        infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        addresses = tuple(
            dict.fromkeys(
                str(info[4][0])
                for info in infos
                if isinstance(info[4], tuple) and info[4]
            )
        )
        if not addresses:
            raise OSError(f"Host '{host}' did not resolve to an address")
        return addresses

    def _is_blocked_host(self, host: str) -> bool:
        lowered = self._normalize_host(host)
        if not lowered:
            return True
        if lowered in {"localhost", "localhost.localdomain"}:
            return True
        if lowered.endswith(".local"):
            return True
        if self._is_blocked_ip(lowered):
            return True
        try:
            addresses = self._resolve_host_addresses(lowered)
        except OSError:
            return True  # Fail-closed: DNS failure blocks the host
        return any(self._is_blocked_ip(address) for address in addresses)

    def _resolve_validated_addresses(self, host: str) -> tuple[str, ...]:
        normalized = self._normalize_host(host)
        allowed_hosts = {
            self._normalize_host(value) for value in self.allow_hosts
        }
        if allowed_hosts and normalized not in allowed_hosts:
            raise _UrlPolicyError(f"Host '{host}' is not allowlisted")
        if not normalized:
            raise _UrlPolicyError(f"Host '{host}' is not allowed")
        if self.block_private_networks and (
            normalized in {"localhost", "localhost.localdomain"}
            or normalized.endswith(".local")
        ):
            raise _UrlPolicyError(f"Host '{host}' is not allowed")

        try:
            addresses = self._resolve_host_addresses(normalized)
        except OSError as exc:
            raise _UrlPolicyError(
                f"Host '{host}' could not be resolved"
            ) from exc
        if self.block_private_networks and any(
            self._is_blocked_ip(address) for address in addresses
        ):
            raise _UrlPolicyError(
                f"Host '{host}' resolves to a private or loopback address"
            )
        return addresses

    def _validate_url(self, raw_url: str) -> tuple[str, str]:
        parsed = urlparse(raw_url)
        scheme = parsed.scheme.lower().strip()
        host = (parsed.hostname or "").strip()
        if not scheme or scheme not in self.allowed_schemes:
            raise ValueError(f"URL scheme '{scheme or 'unknown'}' is not allowed")
        if not host:
            raise ValueError("URL host is missing")
        allowed_hosts = {
            self._normalize_host(value) for value in self.allow_hosts
        }
        if allowed_hosts and self._normalize_host(host) not in allowed_hosts:
            raise ValueError(f"Host '{host}' is not allowlisted")
        if self.block_private_networks and self._is_blocked_host(host):
            raise ValueError(f"Host '{host}' resolves to a private or loopback address")
        return scheme, host

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        url = str(args.get("url", "")).strip()
        extract_mode = (
            str(args.get("extractMode", args.get("extract_mode", "markdown")))
            .strip()
            .lower()
            or "markdown"
        )
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

        try:
            _scheme, _host = self._validate_url(url)
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        class _RedirectLimiter(HTTPRedirectHandler):
            def __init__(self, max_redirects: int, validator) -> None:
                super().__init__()
                self.max_redirects = max_redirects
                self.validator = validator
                self.redirect_count = 0

            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
                self.redirect_count += 1
                if self.redirect_count > self.max_redirects:
                    raise HTTPError(newurl, code, "Too many redirects", headers, fp)
                self.validator(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        redirect_handler = _RedirectLimiter(
            max(0, int(self.max_redirects)), self._validate_url
        )
        opener = build_opener(
            ProxyHandler({}),
            redirect_handler,
            _PinnedHTTPHandler(self._resolve_validated_addresses),
            _PinnedHTTPSHandler(self._resolve_validated_addresses),
        )
        request = Request(url, headers={"User-Agent": "mini-openclaw/0.1"})
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                final_url = str(response.geturl() or url)
                try:
                    _scheme, _host = self._validate_url(final_url)
                except ValueError as exc:
                    return ToolResult.failure(
                        tool_name=self.name,
                        code="E_POLICY_DENIED",
                        message=str(exc),
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )

                content_length_raw = (
                    response.headers.get("Content-Length", "") or ""
                ).strip()
                if content_length_raw:
                    try:
                        if int(content_length_raw) > int(self.max_content_bytes):
                            return ToolResult.failure(
                                tool_name=self.name,
                                code="E_POLICY_DENIED",
                                message=f"Response body exceeds max_content_bytes={self.max_content_bytes}",
                                duration_ms=int((time.monotonic() - started) * 1000),
                            )
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total_read = 0
                max_bytes = max(1024, int(self.max_content_bytes))
                while True:
                    piece = response.read(64 * 1024)
                    if not piece:
                        break
                    chunks.append(piece)
                    total_read += len(piece)
                    if total_read > max_bytes:
                        return ToolResult.failure(
                            tool_name=self.name,
                            code="E_POLICY_DENIED",
                            message=f"Response body exceeds max_content_bytes={self.max_content_bytes}",
                            duration_ms=int((time.monotonic() - started) * 1000),
                        )

                raw = b"".join(chunks)
                content_type = (response.headers.get("Content-Type", "") or "").lower()
                status = int(getattr(response, "status", 200))
                effective_url = final_url
        except _UrlPolicyError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
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
                "url": effective_url,
                "content": text,
                "truncated": truncated,
                "extract_mode": extract_mode,
                "max_chars": max_chars,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
