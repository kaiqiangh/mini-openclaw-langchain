from __future__ import annotations

import os
from typing import Any


def build_optional_callbacks(*, run_id: str) -> list[Any]:
    provider = os.getenv("OBS_TRACING_PROVIDER", "").strip().lower()
    if provider == "":
        return []

    if provider == "langsmith":
        try:
            from langchain.callbacks.tracers import LangChainTracer

            tracer = LangChainTracer()
            tracer.run_name = run_id
            tracer.project_name = os.getenv("LANGSMITH_PROJECT", "mini-openclaw")
            return [tracer]
        except Exception:
            return []

    if provider == "langfuse":
        try:
            from langfuse.callback import CallbackHandler

            handler = CallbackHandler()
            return [handler]
        except Exception:
            return []

    return []

