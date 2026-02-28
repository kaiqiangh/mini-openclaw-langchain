from __future__ import annotations

import importlib
import os
from typing import Any


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return None


def _is_tracing_enabled(provider: str) -> bool:
    override = _parse_bool(os.getenv("OBS_TRACING_ENABLED"))
    if override is not None:
        return override

    if provider == "langsmith":
        # LANGSMITH_TRACING=false should always disable callback wiring.
        langsmith_flag = _parse_bool(os.getenv("LANGSMITH_TRACING"))
        if langsmith_flag is not None:
            return langsmith_flag

        # Compatibility with LangChain naming.
        lc_flag = _parse_bool(os.getenv("LANGCHAIN_TRACING_V2"))
        if lc_flag is not None:
            return lc_flag

    return True


def build_optional_callbacks(*, run_id: str) -> list[Any]:
    provider = os.getenv("OBS_TRACING_PROVIDER", "").strip().lower()
    if provider == "":
        return []
    if not _is_tracing_enabled(provider):
        return []

    if provider == "langsmith":
        try:
            from langchain_core.tracers import LangChainTracer

            tracer = LangChainTracer(
                project_name=os.getenv("LANGSMITH_PROJECT", "mini-openclaw")
            )
            if hasattr(tracer, "run_name"):
                setattr(tracer, "run_name", run_id)
            return [tracer]
        except Exception:
            return []

    if provider == "langfuse":
        try:
            module = importlib.import_module("langfuse.callback")
            handler_cls = getattr(module, "CallbackHandler", None)
            if handler_cls is None:
                return []
            handler = handler_cls()
            return [handler]
        except Exception:
            return []

    return []
