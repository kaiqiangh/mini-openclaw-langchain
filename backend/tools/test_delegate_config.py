from tools.delegate_config import validate_delegate_config, DELEGATE_DEFAULTS


def test_default_config_valid():
    assert validate_delegate_config(DELEGATE_DEFAULTS) is None


def test_enabled_false_is_valid():
    assert validate_delegate_config({**DELEGATE_DEFAULTS, "enabled": False}) is None


def test_max_per_session_zero_is_invalid():
    assert validate_delegate_config({**DELEGATE_DEFAULTS, "max_per_session": 0}) is not None


def test_negative_timeout_is_invalid():
    assert validate_delegate_config({**DELEGATE_DEFAULTS, "default_timeout_seconds": -1}) is not None


def test_delegate_in_scope_is_rejected():
    cfg = {**DELEGATE_DEFAULTS, "allowed_tool_scopes": {"bad": ["delegate", "web_search"]}}
    assert validate_delegate_config(cfg) is not None
