"""Embedding provider protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod

# A search embeds its query on every call, so it waits far less than a save
# does, and after one failure it stops trying for a while.
QUERY_TIMEOUT_SECONDS = 2.0
QUERY_BACKOFF_SECONDS = 30.0


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    def embed_query(self, text: str, timeout: float = QUERY_TIMEOUT_SECONDS) -> list[float]:
        """Embed a search query: one attempt, no autostart, and *timeout* seconds at most per phase."""
        return self.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class EmbeddingsDisabled(RuntimeError):
    """Raised by the ``none`` provider: the store runs on keyword search only."""


class NoEmbedding(EmbeddingProvider):
    """``embedding.provider: none``. Saves skip the vector and search uses FTS5 only."""

    def embed(self, text: str) -> list[float]:
        raise EmbeddingsDisabled("Embeddings are disabled (embedding.provider: none).")
