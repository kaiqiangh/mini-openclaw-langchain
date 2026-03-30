"""Meta-tests for network_safety.yaml — validates YAML schema and runner compatibility."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evals.runner import EvalResult, EvalReport, load_cases, run_evals, EVALS_DIR
from tools.fetch_url_tool import FetchUrlTool


NETWORK_SAFETY_YAML = EVALS_DIR / "network_safety.yaml"


def _load_network_cases() -> list[dict]:
    data = yaml.safe_load(NETWORK_SAFETY_YAML.read_text())
    assert isinstance(data, dict) and "cases" in data, "YAML must have top-level 'cases' key"
    return data["cases"]


class TestNetworkSafetyYAMLSchema:
    """Verify the YAML file is well-formed and every case has required fields."""

    def test_yaml_loads(self):
        cases = _load_network_cases()
        assert len(cases) > 0, "network_safety.yaml must have at least one case"

    def test_every_case_has_name(self):
        for case in _load_network_cases():
            assert "name" in case, f"Case missing 'name': {case}"
            assert isinstance(case["name"], str) and len(case["name"]) > 0

    def test_every_case_has_expect(self):
        for case in _load_network_cases():
            assert "expect" in case, f"Case '{case.get('name')}' missing 'expect'"
            assert case["expect"] in ("allowed", "blocked"), (
                f"Case '{case['name']}' expect must be 'allowed' or 'blocked', got '{case['expect']}'"
            )

    def test_every_case_has_tool(self):
        for case in _load_network_cases():
            assert "tool" in case, f"Case '{case.get('name')}' missing 'tool'"

    def test_ssrf_cases_have_url_in_args(self):
        for case in _load_network_cases():
            assert_type = case.get("assert_type", "policy")
            if assert_type in ("ssrf_block", "ssrf_pass"):
                args = case.get("args", {})
                # "missing URL key" is an intentional edge case
                if "missing" in case.get("name", "").lower():
                    continue
                assert "url" in args, (
                    f"SSRF case '{case['name']}' must have 'url' in args"
                )

    def test_assert_type_values_valid(self):
        valid = {"policy", "ssrf_block", "ssrf_pass"}
        for case in _load_network_cases():
            at = case.get("assert_type", "policy")
            assert at in valid, (
                f"Case '{case['name']}' has invalid assert_type '{at}', expected one of {valid}"
            )

    def test_minimum_case_count(self):
        cases = _load_network_cases()
        assert len(cases) >= 15, (
            f"Expected at least 15 SSRF cases, got {len(cases)}"
        )


class TestNetworkSafetyRunnerExecution:
    """Verify all cases execute through the runner without exceptions."""

    def test_all_evals_pass(self):
        """Every eval case (including network_safety) should pass."""
        report = run_evals(EVALS_DIR)
        assert report.failed == 0, (
            f"{report.failed} eval(s) failed: "
            + ", ".join(r.name for r in report.results if not r.passed)
        )

    def test_safety_score_is_perfect(self):
        """Safety score must be 100%."""
        report = run_evals(EVALS_DIR)
        assert report.safety_score == 1.0, (
            f"Safety score {report.safety_score:.2%} below 100% threshold"
        )


class TestFetchUrlToolDirectly:
    """Direct unit tests of FetchUrlTool SSRF defenses (fast, no network)."""

    @pytest.fixture
    def tool(self):
        return FetchUrlTool()

    def test_blocked_loopback(self, tool):
        with pytest.raises(ValueError, match="private or loopback"):
            tool._validate_url("http://127.0.0.1/")

    def test_blocked_localhost(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://localhost/")

    def test_blocked_private_10(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://10.0.0.1/")

    def test_blocked_aws_metadata(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://169.254.169.254/latest/meta-data/")

    def test_blocked_file_scheme(self, tool):
        with pytest.raises(ValueError, match="scheme"):
            tool._validate_url("file:///etc/passwd")

    def test_blocked_ftp_scheme(self, tool):
        with pytest.raises(ValueError, match="scheme"):
            tool._validate_url("ftp://example.com/")

    def test_allowed_public(self, tool):
        tool._validate_url("https://example.com/")
        tool._validate_url("https://httpbin.org/get")

    def test_blocked_dot_local(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://myservice.local/")

    def test_blocked_empty_url(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("")

    def test_blocked_multicast(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://224.0.0.1/")

    def test_blocked_unspecified(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://0.0.0.0/")

    def test_blocked_ipv6_loopback(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://[::1]/")

    def test_blocked_decimal_encoding(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://2130706433/")

    def test_blocked_hex_encoding(self, tool):
        with pytest.raises(ValueError):
            tool._validate_url("http://0x7f000001/")
