"""Hybrid search combining FTS5 keyword search and semantic vector search."""

from __future__ import annotations

import logging
from typing import Any

from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.embeddings.base import EmbeddingProvider, EmbeddingsDisabled

logger = logging.getLogger(__name__)

# Specificity bonus added to a normalised score by scope layer. A bias, not a
# hard gate: a much stronger org/global hit can still outrank a weak project one.
SCOPE_BONUS = {3: 0.15, 2: 0.05, 1: 0.0, 0: 0.0}


def apply_scope_bonus(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the per-layer specificity bonus to each row's score, then re-sort.

    Rows without a ``scope_rank`` are left untouched (no-op for unscoped search).
    """
    for r in rows:
        rank = r.get("scope_rank")
        if rank is not None:
            r["score"] = r.get("score", 0.0) + SCOPE_BONUS.get(rank, 0.0)
    return sorted(rows, key=lambda x: x.get("score", 0.0), reverse=True)


def _normalise(results: list[dict[str, Any]]) -> None:
    """Scale scores in place by their maximum, so the best is 1.0; all zero when none is positive."""
    if not results:
        return
    best = max(r["score"] for r in results)
    for r in results:
        r["score"] = r["score"] / best if best > 0 else 0.0


def merge_results(
    fts_results: list[dict[str, Any]],
    vec_results: list[dict[str, Any]],
    fts_weight: float = 0.3,
    vec_weight: float = 0.7,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Normalise positive per-backend scores by their maximum, then weight.

    Vector scores are reciprocal L2 distance, ``1 / (1 + distance)``, rather
    than cosine similarity. Maximum normalisation preserves their ordering
    and relative strengths before combining them with positive FTS ranks.
    """
    _normalise(fts_results)

    _normalise(vec_results)

    scores: dict[str, dict[str, Any]] = {}
    for r in fts_results:
        rid = r["id"]
        scores[rid] = dict(r)
        scores[rid]["score"] = fts_weight * r["score"]
    for r in vec_results:
        rid = r["id"]
        if rid in scores:
            scores[rid]["score"] += vec_weight * r["score"]
        else:
            scores[rid] = dict(r)
            scores[rid]["score"] = vec_weight * r["score"]

    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:limit]


def tiered_search(
    repo: MemoryRepository,
    embedding_provider: EmbeddingProvider | None,
    query: str,
    limit: int = 5,
    project: str | None = None,
    source: str | None = None,
    org: str | None = None,
    include_org: bool = True,
    include_global: bool = True,
) -> list[dict[str, Any]]:
    """Keyword and vector search on every query, merged by score.

    The query is embedded once. When the provider is missing, down or slow the
    keyword results stand alone: a search never raises or waits for it beyond
    the query timeout, and a failure skips the provider for a while.
    """
    fts_results = repo.fts_search(
        query,
        limit=limit * 2,
        project=project,
        source=source,
        org=org,
        include_org=include_org,
        include_global=include_global,
    )

    _normalise(fts_results)

    results = fts_results
    if embedding_provider is not None:
        try:
            query_vec = embedding_provider.embed_query(query)
        except EmbeddingsDisabled:
            pass
        except Exception:  # the provider has already logged why
            logger.debug("Query embedding failed; keyword results only", exc_info=True)
        else:
            vec_results = repo.vector_search(
                query_vec,
                limit=limit * 2,
                project=project,
                source=source,
                org=org,
                include_org=include_org,
                include_global=include_global,
            )
            results = merge_results(fts_results, vec_results, limit=limit * 2)

    if org is not None:
        results = apply_scope_bonus(results)
    return results[:limit]
