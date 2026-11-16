"""Sanitise all outbound embedding text, including queries and batches."""

from __future__ import annotations

import logging
import time

from arcane.infra.embeddings.base import (
    QUERY_BACKOFF_SECONDS,
    QUERY_TIMEOUT_SECONDS,
    EmbeddingProvider,
    EmbeddingsDisabled,
)
from arcane.infra.redaction import redact

logger = logging.getLogger(__name__)


class QueryEmbeddingUnavailable(RuntimeError):
    """A query embedding was skipped because the provider failed a moment ago."""


class RedactingEmbedding(EmbeddingProvider):
    """Apply the vault's redaction policy before delegating to a backend."""

    def __init__(self, provider: EmbeddingProvider, extra_patterns: list[str]) -> None:
        self._provider = provider
        self._extra_patterns = extra_patterns
        self._query_retry_at = 0.0

    def embed(self, text: str) -> list[float]:
        return self._provider.embed(redact(text, self._extra_patterns))

    def embed_query(self, text: str, timeout: float = QUERY_TIMEOUT_SECONDS) -> list[float]:
        """Embed a search query, and after a failure skip the provider for ``QUERY_BACKOFF_SECONDS``.

        A provider that is down or hanging then costs one wait, not one per search.
        """
        if time.monotonic() < self._query_retry_at:
            raise QueryEmbeddingUnavailable("embedding provider failed recently")
        try:
            return self._provider.embed_query(redact(text, self._extra_patterns), timeout)
        except EmbeddingsDisabled:
            raise
        except Exception as exc:
            self._query_retry_at = time.monotonic() + QUERY_BACKOFF_SECONDS
            logger.warning(
                "Query embedding failed (%s) — searching by keyword for %ds.", exc, int(QUERY_BACKOFF_SECONDS)
            )
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._provider.embed_batch([redact(text, self._extra_patterns) for text in texts])
