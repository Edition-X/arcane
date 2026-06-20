"""Hybrid search combining FTS5 keyword search and semantic vector search."""

from __future__ import annotations

from typing import Any

from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.embeddings.base import EmbeddingProvider

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


def merge_results(
    fts_results: list[dict[str, Any]],
    vec_results: list[dict[str, Any]],
    fts_weight: float = 0.3,
    vec_weight: float = 0.7,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Merge FTS5 and vector search results with weighted scoring."""
    if fts_results:
        max_fts = max(r["score"] for r in fts_results) or 1.0
        for r in fts_results:
            r["score"] = r["score"] / max_fts if max_fts > 0 else 0.0

    if vec_results:
        max_vec = max(r["score"] for r in vec_results) or 1.0
        for r in vec_results:
            r["score"] = r["score"] / max_vec if max_vec > 0 else 0.0

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
    min_fts_results: int = 3,
    project: str | None = None,
    source: str | None = None,
    org: str | None = None,
    include_org: bool = True,
    include_global: bool = True,
) -> list[dict[str, Any]]:
    """FTS-first tiered search — only calls embed when FTS results are sparse."""
    fts_results = repo.fts_search(
        query,
        limit=limit * 2,
        project=project,
        source=source,
        org=org,
        include_org=include_org,
        include_global=include_global,
    )

    if fts_results:
        max_score = max(r["score"] for r in fts_results) or 1.0
        for r in fts_results:
            r["score"] = r["score"] / max_score if max_score > 0 else 0.0

    if len(fts_results) >= min_fts_results or embedding_provider is None:
        results = fts_results
    else:
        try:
            query_vec = embedding_provider.embed(query)
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
        except Exception:
            results = fts_results

    if org is not None:
        results = apply_scope_bonus(results)
    return results[:limit]


def hybrid_search(
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
    """Run FTS5 and optionally vector search, merge results."""
    fts_results = repo.fts_search(
        query,
        limit=limit * 2,
        project=project,
        source=source,
        org=org,
        include_org=include_org,
        include_global=include_global,
    )

    if embedding_provider is None:
        if fts_results:
            max_score = max(r["score"] for r in fts_results) or 1.0
            for r in fts_results:
                r["score"] = r["score"] / max_score if max_score > 0 else 0.0
        results = fts_results
    else:
        query_vec = embedding_provider.embed(query)
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
