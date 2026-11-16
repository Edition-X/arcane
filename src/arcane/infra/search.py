"""Hybrid search combining FTS5 keyword search and semantic vector search."""

from __future__ import annotations

import logging
from typing import Any

from arcane.domain.scope import Reach
from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.embeddings.base import EmbeddingProvider, EmbeddingsDisabled

logger = logging.getLogger(__name__)

# Specificity bonus added to a normalised score by scope layer. A bias, not a
# hard gate: a much stronger org/global hit can still outrank a weak project one.
SCOPE_BONUS = {3: 0.15, 2: 0.05, 1: 0.0, 0: 0.0}
# After widening past the project, relevance decides and the local bonus only
# breaks near-ties: a strong hit from another project beats a weak local one.
WIDENED_SCOPE_BONUS = {3: 0.03, 2: 0.02, 1: 0.0, 0: 0.0}

FTS_WEIGHT = 0.3
VEC_WEIGHT = 0.7
# Added to a row that holds every key word of the query. Such a row may have
# little vector score, and a vector-only row scores up to VEC_WEIGHT, so the
# bonus has to exceed that to lead it. It also covers the widest scope gap
# (the 0.15 project bonus), so a vector-only neighbour from a nearer layer
# cannot pass it either. Every reach gets it: a keyword hit that names the
# whole query is strong evidence in the project or across the org.
STRICT_MATCH_BONUS = VEC_WEIGHT + SCOPE_BONUS[3]


def apply_scope_bonus(rows: list[dict[str, Any]], bonus: dict[int, float] = SCOPE_BONUS) -> list[dict[str, Any]]:
    """Add the per-layer specificity bonus to each row's score, then re-sort.

    Rows without a ``scope_rank`` are left untouched (no-op for unscoped search).
    """
    for r in rows:
        rank = r.get("scope_rank")
        if rank is not None:
            r["score"] = r.get("score", 0.0) + bonus.get(rank, 0.0)
    return sorted(rows, key=lambda x: x.get("score", 0.0), reverse=True)


def _normalise(results: list[dict[str, Any]]) -> None:
    """Scale scores in place by their maximum, so the best is 1.0; all zero when none is positive."""
    if not results:
        return
    best = max(r["score"] for r in results)
    for r in results:
        r["score"] = r["score"] / best if best > 0 else 0.0


def _normalise_range(results: list[dict[str, Any]]) -> None:
    """Scale scores in place onto 0..1 between their minimum and maximum; all 1.0 when they are equal."""
    if not results:
        return
    low = min(r["score"] for r in results)
    high = max(r["score"] for r in results)
    for r in results:
        r["score"] = (r["score"] - low) / (high - low) if high > low else 1.0


def apply_strict_bonus(rows: list[dict[str, Any]], strict_ids: set[str]) -> None:
    """Add ``STRICT_MATCH_BONUS`` in place to each row whose id is in *strict_ids*."""
    for r in rows:
        if r["id"] in strict_ids:
            r["score"] += STRICT_MATCH_BONUS


def merge_results(
    fts_results: list[dict[str, Any]],
    vec_results: list[dict[str, Any]],
    fts_weight: float = FTS_WEIGHT,
    vec_weight: float = VEC_WEIGHT,
    limit: int = 5,
    strict_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Normalise each backend's scores, then weight.

    FTS ranks are scaled by their maximum. Vector scores are reciprocal L2
    distance, ``1 / (1 + distance)``, which sit close together for every
    neighbour, so they are spread over their range instead: scaled by the
    maximum, a neighbour sharing no word with the query scored near 1.0 and
    outranked an exact keyword hit. Rows in *strict_ids*, which match every key
    word of the query, then get ``STRICT_MATCH_BONUS`` so they lead the rest.
    """
    _normalise(fts_results)

    _normalise_range(vec_results)

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

    ranked = list(scores.values())
    apply_strict_bonus(ranked, strict_ids or set())
    ranked.sort(key=lambda x: x["score"], reverse=True)
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
    reach: Reach = "layers",
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
        reach=reach,
    )

    _normalise(fts_results)
    strict_ids = repo.strict_match_ids(
        query,
        project=project,
        source=source,
        org=org,
        include_org=include_org,
        include_global=include_global,
        reach=reach,
    )

    results: list[dict[str, Any]] | None = None
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
                reach=reach,
            )
            results = merge_results(fts_results, vec_results, limit=limit * 2, strict_ids=strict_ids)

    if results is None:
        results = fts_results
        apply_strict_bonus(results, strict_ids)

    if org is not None:
        results = apply_scope_bonus(results, SCOPE_BONUS if reach == "layers" else WIDENED_SCOPE_BONUS)
    return results[:limit]
