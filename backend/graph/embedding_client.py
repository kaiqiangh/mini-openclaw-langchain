from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from config import EmbeddingProvider, SecretConfig


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class EmbeddingClient:
    secrets: SecretConfig
    timeout_seconds: int = 20

    def _post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text)

    @staticmethod
    def _to_float_vector(raw: Any) -> list[float]:
        if not isinstance(raw, list):
            return []
        values: list[float] = []
        for item in raw:
            try:
                values.append(float(item))
            except Exception:
                values.append(0.0)
        return values

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        if not self.secrets.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for openai embedding provider"
            )
        payload = {
            "model": self.secrets.embedding_model,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self.secrets.openai_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.secrets.openai_base_url.rstrip('/')}/embeddings"
        response = self._post_json(url, payload, headers)
        rows = response.get("data", [])
        if not isinstance(rows, list):
            raise RuntimeError(
                "Invalid embeddings response format from OpenAI-compatible endpoint"
            )

        rows_sorted = sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: int(row.get("index", 0)),
        )
        vectors = [
            self._to_float_vector(row.get("embedding", [])) for row in rows_sorted
        ]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding response size mismatch")
        return vectors

    def _embed_google(self, texts: list[str]) -> list[list[float]]:
        if not self.secrets.google_api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is required for google_ai_studio embedding provider"
            )
        model = self.secrets.google_embedding_model.strip()
        model_full = model if model.startswith("models/") else f"models/{model}"

        headers = {"Content-Type": "application/json"}

        if len(texts) == 1:
            payload = {
                "model": model_full,
                "content": {"parts": [{"text": texts[0]}]},
            }
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"{model_full}:embedContent?key={self.secrets.google_api_key}"
            )
            response = self._post_json(url, payload, headers)
            embedding = response.get("embedding", {})
            if not isinstance(embedding, dict):
                raise RuntimeError(
                    "Invalid embedContent response from Google AI Studio"
                )
            return [self._to_float_vector(embedding.get("values", []))]

        requests_payload = [
            {
                "model": model_full,
                "content": {"parts": [{"text": text}]},
            }
            for text in texts
        ]
        payload = {"requests": requests_payload}
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{model_full}:batchEmbedContents?key={self.secrets.google_api_key}"
        )
        response = self._post_json(url, payload, headers)
        embeddings = response.get("embeddings", [])
        if not isinstance(embeddings, list):
            raise RuntimeError(
                "Invalid batchEmbedContents response from Google AI Studio"
            )

        vectors = []
        for row in embeddings:
            if not isinstance(row, dict):
                vectors.append([])
                continue
            vectors.append(self._to_float_vector(row.get("values", [])))
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding response size mismatch")
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        provider = self.secrets.embedding_provider
        if provider == EmbeddingProvider.OPENAI:
            return self._embed_openai(texts)
        if provider == EmbeddingProvider.GOOGLE_AI_STUDIO:
            return self._embed_google(texts)
        raise RuntimeError(f"Unsupported embedding provider: {provider}")
