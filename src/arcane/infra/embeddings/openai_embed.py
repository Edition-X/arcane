"""OpenAI embedding provider."""

from __future__ import annotations

import httpx

from arcane.infra.embeddings.base import EmbeddingProvider

_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
# The embeddings API accepts up to 2048 inputs per request.
_MAX_BATCH = 2048


class OpenAIEmbedding(EmbeddingProvider):
    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or ""
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        # Reused so each embed skips a fresh TLS handshake with the API.
        if self._client is None:
            self._client = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {self.api_key}"})
        return self._client

    def _request(self, inputs: str | list[str]) -> list[list[float]]:
        resp = self._http().post(_EMBEDDINGS_URL, json={"model": self.model, "input": inputs})
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda item: item["index"])
        return [list(item["embedding"]) for item in data]

    def embed(self, text: str) -> list[float]:
        return self._request(text)[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH):
            vectors.extend(self._request(texts[start : start + _MAX_BATCH]))
        return vectors
