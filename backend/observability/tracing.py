from __future__ import annotations

import importlib
import os
from typing import Any


def build_optional_callbacks(*, run_id: str) -> list[Any]:
    provider = os.getenv("OBS_TRACING_PROVIDER", "").strip().lower()
    if provider == "":
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
