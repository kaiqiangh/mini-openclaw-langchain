"""Tests for hooks runtime config."""
from config import RuntimeConfig, HooksRuntimeConfig


class TestHooksConfig:
    def test_default_hooks_config(self):
        config = RuntimeConfig()
        assert config.hooks.enabled is True
        assert config.hooks.default_timeout_ms == 10000

    def test_hooks_can_be_disabled(self):
        config = RuntimeConfig()
        config.hooks.enabled = False
        assert config.hooks.enabled is False

    def test_hooks_custom_timeout(self):
        config = RuntimeConfig()
        config.hooks.default_timeout_ms = 5000
        assert config.hooks.default_timeout_ms == 5000


class TestHooksRuntimeConfig:
    def test_standalone_creation(self):
        h = HooksRuntimeConfig(enabled=False, default_timeout_ms=20000)
        assert h.enabled is False
        assert h.default_timeout_ms == 20000

    def test_fields_have_defaults(self):
        h = HooksRuntimeConfig()
        assert h.enabled is True
        assert h.default_timeout_ms == 10000
