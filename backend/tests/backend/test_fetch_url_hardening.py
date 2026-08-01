from __future__ import annotations

import io
import socket
from pathlib import Path

import pytest

from tools.base import ToolContext
from tools.fetch_url_tool import FetchUrlTool, _PinnedHTTPConnection


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, trigger_type="chat")


def test_fetch_url_rejects_disallowed_schemes(tmp_path: Path):
    tool = FetchUrlTool(timeout_seconds=1)
    result = tool.run({"url": "file:///etc/passwd"}, _context(tmp_path))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"


def test_fetch_url_rejects_loopback_hosts(tmp_path: Path):
    tool = FetchUrlTool(timeout_seconds=1, block_private_networks=True)
    result = tool.run({"url": "http://localhost:8080"}, _context(tmp_path))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"


def test_fetch_url_enforces_content_size_limit(tmp_path: Path, monkeypatch):
    tool = FetchUrlTool(timeout_seconds=1, max_content_bytes=12)

    class _FakeResponse:
        status = 200
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": "1000",
        }

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def read(self, n=0) -> bytes:  # noqa: ARG002
            return b""

        def geturl(self) -> str:
            return "https://example.com"

    class _FakeOpener:
        def open(self, request, timeout=0):  # noqa: D401, ARG002
            return _FakeResponse()

    import tools.fetch_url_tool as fetch_module

    monkeypatch.setattr(
        fetch_module, "build_opener", lambda *args, **kwargs: _FakeOpener()
    )
    result = tool.run({"url": "https://example.com"}, _context(tmp_path))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"


def test_fetch_url_enforces_redirect_limit(tmp_path: Path, monkeypatch):
    tool = FetchUrlTool(timeout_seconds=1, max_redirects=1, max_content_bytes=1024)

    def _fake_build_opener(*handlers):
        handler = handlers[1]
        class _FakeOpener:
            def open(self, request, timeout=0):  # noqa: D401, ARG002
                headers: dict[str, str] = {}
                handler.redirect_request(
                    request,
                    io.BytesIO(b""),
                    302,
                    "Found",
                    headers,
                    "https://example.com/a",
                )
                handler.redirect_request(
                    request,
                    io.BytesIO(b""),
                    302,
                    "Found",
                    headers,
                    "https://example.com/b",
                )
                raise AssertionError("expected redirect handler to stop execution")

        return _FakeOpener()

    import tools.fetch_url_tool as fetch_module

    monkeypatch.setattr(fetch_module, "build_opener", _fake_build_opener)
    result = tool.run({"url": "https://example.com"}, _context(tmp_path))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_HTTP"


def test_fetch_url_rejects_dns_rebinding_before_connect(tmp_path: Path, monkeypatch):
    tool = FetchUrlTool(block_private_networks=True)
    public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))
    private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))
    resolutions = iter([(public,), (private,)])
    monkeypatch.setattr(
        "tools.fetch_url_tool.socket.getaddrinfo",
        lambda *args, **kwargs: next(resolutions),
    )

    tool._validate_url("http://example.com/")
    connection = _PinnedHTTPConnection(
        "example.com", resolver=tool._resolve_validated_addresses
    )
    connect_calls: list[tuple[object, ...]] = []
    connection._create_connection = lambda *args: connect_calls.append(args)  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="private or loopback"):
        connection.connect()
    assert connect_calls == []
