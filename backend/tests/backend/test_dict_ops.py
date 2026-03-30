"""Tests for shared dict operations."""
from utils.dict_ops import deep_merge, deep_diff


def test_deep_merge_simple():
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_nested():
    base = {"a": {"x": 1, "y": 2}}
    override = {"a": {"y": 3, "z": 4}}
    result = deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 3, "z": 4}}


def test_deep_merge_override_non_dict():
    assert deep_merge({"a": 1}, {"a": {"b": 2}}) == {"a": {"b": 2}}


def test_deep_merge_empty():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
    assert deep_merge({"a": 1}, {}) == {"a": 1}


def test_deep_diff_identical():
    assert deep_diff({"a": 1}, {"a": 1}) == {}


def test_deep_diff_changed():
    result = deep_diff({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert result == {"b": 2}


def test_deep_diff_nested():
    result = deep_diff(
        {"a": {"x": 1, "y": 2}},
        {"a": {"x": 1, "y": 3}},
    )
    assert result == {"a": {"y": 2}}


def test_deep_diff_added_key():
    result = deep_diff({"a": 1, "b": 2}, {"a": 1})
    assert result == {"b": 2}
