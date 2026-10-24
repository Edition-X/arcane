"""Embedding provider protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class EmbeddingsDisabled(RuntimeError):
    """Raised by the ``none`` provider: the store runs on keyword search only."""


class NoEmbedding(EmbeddingProvider):
    """``embedding.provider: none``. Saves skip the vector and search uses FTS5 only."""

    def embed(self, text: str) -> list[float]:
        raise EmbeddingsDisabled("Embeddings are disabled (embedding.provider: none).")
