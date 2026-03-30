"""Minimal runner: reads code from stdin, executes with restricted builtins, prints JSON result."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

_ESCAPE_PATTERNS = (
    "__class__",
    "__bases__",
    "__subclasses__",
    "__mro__",
    "__import__",
    "__builtins__",
    "getattr(",
    "setattr(",
    "delattr(",
    "globals()",
    "locals()",
    "vars()",
    "dir()",
    "open(",
    "compile(",
    "eval(",
    "exec(",
)

SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "enumerate": enumerate, "filter": filter,
    "float": float, "format": format, "frozenset": frozenset,
    "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "print": print, "range": range, "reversed": reversed,
    "round": round, "set": set, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "type": type, "zip": zip,
}


def _contains_escape_attempt(code: str) -> bool:
    lowered = code.lower()
    return any(pattern in lowered for pattern in _ESCAPE_PATTERNS)


def main() -> None:
    code = sys.stdin.read()
    if not code.strip():
        json.dump({"ok": False, "error": "No code provided"}, sys.stdout)
        sys.exit(1)

    if _contains_escape_attempt(code):
        json.dump(
            {"ok": False, "error": "Code contains disallowed patterns (introspection/escape)"},
            sys.stdout,
        )
        sys.exit(1)

    safe_globals = {"__builtins__": SAFE_BUILTINS}
    safe_locals: dict = {}
    buffer = io.StringIO()

    try:
        with redirect_stdout(buffer):
            exec(code, safe_globals, safe_locals)
    except Exception as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout)
        sys.exit(1)

    json.dump({"ok": True, "output": buffer.getvalue().strip()}, sys.stdout)


if __name__ == "__main__":
    main()
