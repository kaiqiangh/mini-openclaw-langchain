"""Shared dictionary operations."""
from __future__ import annotations
from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge override into base, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def deep_diff(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Return keys in candidate that differ from baseline (nested-aware)."""
    diff: dict[str, Any] = {}
    for key, value in candidate.items():
        baseline_value = baseline.get(key)
        if isinstance(value, dict) and isinstance(baseline_value, dict):
            nested = deep_diff(value, baseline_value)
            if nested:
                diff[key] = nested
            continue
        if value != baseline_value:
            diff[key] = value
    return diff
