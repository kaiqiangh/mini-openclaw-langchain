from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_ALLOWED_MSGPACK_MODULES = (
    ("config", "LLMDriver"),
    ("config", "LLMProfile"),
    ("config", "LlmFallbackPolicy"),
    ("graph.runtime_types", "RuntimeErrorInfo"),
    ("graph.runtime_types", "RuntimeRequest"),
    ("graph.runtime_types", "ToolExecutionEnvelope"),
    ("llm_routing", "ResolvedLlmCandidate"),
    ("llm_routing", "ResolvedLlmRoute"),
)


def build_checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
