"""Tests for fetch_url DNS fail-closed behavior."""
from unittest.mock import patch

from tools.fetch_url_tool import FetchUrlTool


def test_blocked_host_on_dns_failure():
    """DNS resolution failure must block, not allow."""
    tool = FetchUrlTool(block_private_networks=True)
    with patch("tools.fetch_url_tool.socket.getaddrinfo", side_effect=OSError("DNS failure")):
        result = tool._is_blocked_host("example.com")
        assert result is True, "DNS failure must result in blocked host (fail-closed)"


def test_allowed_host_on_successful_public_dns():
    """Public host with successful DNS should not be blocked."""
    tool = FetchUrlTool(block_private_networks=True)
    # 8.8.8.8 is a public IP, should not be blocked
    result = tool._is_blocked_host("dns.google")
    assert result is False, "Public host should not be blocked"
