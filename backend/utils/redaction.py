from __future__ import annotations

import json
import re
from typing import Any


_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"\b(?:api[_-]?key|token|authorization)\s*[:=]\s*['\"]?([A-Za-z0-9._-]{8,})['\"]?",
        re.I,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}\b", re.I),
]


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(
                flag in lowered
                for flag in (
                    "api_key",
                    "apikey",
                    "token",
                    "secret",
                    "authorization",
                    "password",
                )
            ):
                output[str(key)] = "[REDACTED]"
            else:
                output[str(key)] = redact_value(item)
        return output
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(redact_value(payload), ensure_ascii=False)
