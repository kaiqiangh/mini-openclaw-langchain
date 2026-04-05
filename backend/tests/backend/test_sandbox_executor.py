"""Tests for SandboxExecutor."""
import os
import __main__
import pytest
from unittest.mock import patch, MagicMock

from tools.sandbox_executor import SandboxConfig, SandboxExecutor, _docker_available
from tools.python_repl_tool import _get_mp_context


class TestSandboxConfig:
    def test_default_mode_is_in_process(self):
        config = SandboxConfig()
        assert config.mode == "in_process"

    def test_from_env_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REPL_SANDBOX_MODE", None)
            config = SandboxConfig.from_env()
            assert config.mode == "in_process"

    def test_from_env_docker(self):
        with patch.dict(os.environ, {"REPL_SANDBOX_MODE": "docker"}):
            config = SandboxConfig.from_env()
            assert config.mode == "docker"

    def test_from_env_auto(self):
        with patch.dict(os.environ, {"REPL_SANDBOX_MODE": "auto"}):
            config = SandboxConfig.from_env()
            assert config.mode == "auto"

    def test_custom_image(self):
        with patch.dict(os.environ, {"REPL_SANDBOX_IMAGE": "my-sandbox:v2"}):
            config = SandboxConfig.from_env()
            assert config.image == "my-sandbox:v2"


class TestSandboxExecutor:
    def test_in_process_mode_uses_multiprocessing(self):
        config = SandboxConfig(mode="in_process")
        executor = SandboxExecutor(config)
        assert executor.use_docker is False

    def test_docker_mode_always_uses_docker(self):
        config = SandboxConfig(mode="docker")
        executor = SandboxExecutor(config)
        assert executor.use_docker is True

    def test_auto_mode_checks_docker(self):
        config = SandboxConfig(mode="auto")
        executor = SandboxExecutor(config)
        with patch("tools.sandbox_executor._docker_available", return_value=False):
            assert executor.use_docker is False

    def test_in_process_execution(self):
        config = SandboxConfig(mode="in_process")
        executor = SandboxExecutor(config)
        result = executor.run("print(2 + 2)")
        assert result["ok"] is True
        assert "4" in result["output"]

    def test_in_process_escape_blocked(self):
        config = SandboxConfig(mode="in_process")
        executor = SandboxExecutor(config)
        result = executor.run("__class__.__bases__")
        assert result["ok"] is False
        assert "disallowed" in result["error"].lower()

    def test_in_process_error_handling(self):
        config = SandboxConfig(mode="in_process")
        executor = SandboxExecutor(config)
        result = executor.run("1 / 0")
        assert result["ok"] is False
        assert "division" in result["error"].lower() or "zero" in result["error"].lower()


class TestMultiprocessingContext:
    def test_prefers_forkserver_on_linux_when_spawn_is_supported(self, monkeypatch):
        monkeypatch.setattr("tools.python_repl_tool.sys.platform", "linux")
        monkeypatch.setattr("tools.python_repl_tool.mp.get_all_start_methods", lambda: ["fork", "forkserver", "spawn"])
        monkeypatch.setattr(__main__, "__file__", __file__, raising=False)

        ctx = _get_mp_context()

        assert ctx.get_start_method() == "forkserver"

    def test_falls_back_to_fork_when_main_module_cannot_be_reimported(self, monkeypatch):
        monkeypatch.setattr("tools.python_repl_tool.sys.platform", "linux")
        monkeypatch.setattr("tools.python_repl_tool.mp.get_all_start_methods", lambda: ["fork", "forkserver", "spawn"])
        monkeypatch.setattr(__main__, "__file__", "<stdin>", raising=False)

        ctx = _get_mp_context()

        assert ctx.get_start_method() == "fork"


class TestDockerAvailable:
    def test_returns_false_when_docker_not_in_path(self):
        with patch("tools.sandbox_executor.shutil.which", return_value=None):
            assert _docker_available("some-image") is False

    def test_returns_false_when_image_not_found(self):
        with patch("tools.sandbox_executor.shutil.which", return_value="/usr/bin/docker"):
            mock_result = MagicMock()
            mock_result.returncode = 1
            with patch("tools.sandbox_executor.subprocess.run", return_value=mock_result):
                assert _docker_available("nonexistent-image") is False
