"""Sanitise all outbound embedding text, including queries and batches."""

from __future__ import annotations

from arcane.infra.embeddings.base import EmbeddingProvider
from arcane.infra.redaction import redact


class RedactingEmbedding(EmbeddingProvider):
    """Apply the vault's redaction policy before delegating to a backend."""

    def __init__(self, provider: EmbeddingProvider, extra_patterns: list[str]) -> None:
        self._provider = provider
        self._extra_patterns = extra_patterns

    def embed(self, text: str) -> list[float]:
        return self._provider.embed(redact(text, self._extra_patterns))

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._provider.embed_batch([redact(text, self._extra_patterns) for text in texts])
