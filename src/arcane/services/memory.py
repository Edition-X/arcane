"""MemoryService — orchestrates memory operations."""

from __future__ import annotations

import logging
import math
import os
import struct
from datetime import date
from typing import Any

from arcane.domain.enums import RelationType
from arcane.domain.models import Memory, RawMemoryInput
from arcane.domain.scope import GLOBAL_ORG, resolve_read_project, resolve_write_scope, slugify
from arcane.infra.db.ids import IdentifierResolutionError, resolve_entity_id
from arcane.infra.db.schema import create_vec_table
from arcane.infra.markdown import remove_session_memory, write_session_memory
from arcane.infra.redaction import redact, redact_values
from arcane.infra.search import hybrid_search, tiered_search
from arcane.services.container import ServiceContainer

logger = logging.getLogger(__name__)

# Texts sent to the embedding provider per request during a reindex.
REINDEX_BATCH_SIZE = 64


class DimensionMismatchError(Exception):
    def __init__(self, stored_dim: int, new_dim: int):
        self.stored_dim = stored_dim
        self.new_dim = new_dim
        super().__init__(
            f"Embedding dimension mismatch: database has {stored_dim}, "
            f"provider returned {new_dim}. Run 'arcane reindex' to rebuild."
        )


def _embedding_text(
    title: str,
    what: str,
    why: str | None,
    impact: str | None,
    tags: list[str],
    extra_patterns: list[str] | None = None,
) -> str:
    """Build the text string that is fed to the embedding model."""
    return redact(f"{title} {what} {why or ''} {impact or ''} {' '.join(tags)}", extra_patterns)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity, 0.0 when either vector is degenerate."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryService:
    """Main orchestrator for memory operations."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    @property
    def vectors_available(self) -> bool:
        return self.c.memory_repo._has_vec_table()

    def _ensure_vectors(self, embedding: list[float]) -> bool:
        """Ensure the vector table exists and matches *embedding* dimension.

        Returns ``True`` when the table is ready, ``False`` on dimension mismatch.
        """
        dim = len(embedding)
        stored_dim = self.c.memory_repo.get_embedding_dim()
        if stored_dim is None:
            self.c.memory_repo.set_embedding_dim(dim)
            create_vec_table(self.c.db, dim)
            self.c.memory_repo.invalidate_vec_cache()
            return True
        if stored_dim != dim:
            logger.warning(
                "Embedding dimension mismatch: DB has %d, provider returned %d. Run 'arcane reindex' to rebuild.",
                stored_dim,
                dim,
            )
            return False
        if not self.c.memory_repo._has_vec_table():
            create_vec_table(self.c.db, dim)
            self.c.memory_repo.invalidate_vec_cache()
        return True

    def _merge_tags(self, existing: list[str], extra: list[str]) -> list[str]:
        combined = existing[:]
        existing_norm = {t.lower() for t in existing}
        for tag in extra:
            if tag.lower() not in existing_norm:
                combined.append(tag)
                existing_norm.add(tag.lower())
        return combined

    def _details_warnings(self, raw: RawMemoryInput) -> list[str]:
        """Warn when decision/bug memories lack details — guidance only."""
        category = (raw.category or "").strip().lower()
        if category in {"decision", "bug"} and not (raw.details or "").strip():
            return [
                f"'{category}' memories should include details. "
                "Capture context, options considered, decision, tradeoffs, and follow-up."
            ]
        return []

    def _resolve_journey(self, journey_id: str | None, warnings: list[str]) -> str | None:
        """Resolve a caller-supplied journey ID or prefix to the stored full ID.

        A bad journey reference must not lose the save, so it becomes a warning
        and the memory is stored unlinked.
        """
        if not journey_id:
            return None
        try:
            full_id = resolve_entity_id(self.c.db, "journey", journey_id)
        except IdentifierResolutionError as exc:
            warnings.append(f"journey_not_linked: {exc} The memory was saved without a journey link.")
            return None
        if full_id is None:
            warnings.append(
                f"journey_not_found: no journey matches '{journey_id}'. The memory was saved without a journey link."
            )
        return full_id

    @staticmethod
    def _near_duplicate_message(title: str, memory_id: str, score: float | None) -> str:
        score_part = f", similarity {score:.2f}" if score is not None else ""
        return (
            f"near_duplicate: existing memory '{title}' (id {memory_id}{score_part}) "
            "covers similar ground. Consider updating it instead of creating a new one."
        )

    def _near_duplicate_warning(
        self,
        raw: RawMemoryInput,
        project: str,
        org: str,
        fts_candidates: list[dict[str, Any]],
        embedding: list[float] | None,
    ) -> str | None:
        """Return a warning when the new memory is semantically close to an existing one.

        *embedding* is the new memory's own stored embedding, so the check
        compares like with like and costs no extra embedding call. Advisory
        only — a false positive must never lose a save, so every failure path
        degrades to ``None`` (or to a normalised-title match when embeddings
        are down). The search is confined to the exact scope layer being
        written, mirroring the exact-title dedup.
        """
        if embedding is None:
            # Embeddings unavailable — fall back to a normalised-title match
            # over the FTS candidates so the check still does something.
            norm_title = slugify(raw.title)
            for cand in fts_candidates:
                if slugify(cand["title"]) == norm_title:
                    return self._near_duplicate_message(cand["title"], cand["id"], None)
            return None

        try:
            if org:
                hits = self.c.memory_repo.vector_search(
                    embedding,
                    limit=3,
                    project=project,
                    org=org,
                    include_org=not project,
                    include_global=False,
                )
            else:
                hits = self.c.memory_repo.vector_search(embedding, limit=3, project=project)

            # Re-score with true cosine similarity: backends like nomic return
            # unnormalised vectors, so the L2-derived `score` from vector_search
            # ranks fine but is meaningless as an absolute threshold.
            best: tuple[float, dict[str, Any]] | None = None
            for hit in hits:
                stored = self.c.memory_repo.get_vector(hit["rowid"])
                if stored is None:
                    continue
                sim = _cosine_similarity(embedding, stored)
                if best is None or sim > best[0]:
                    best = (sim, hit)
        except Exception:
            logger.debug("Near-duplicate vector search failed; skipping check", exc_info=True)
            return None

        if best is not None and best[0] >= self.c.config.dedup.threshold:
            return self._near_duplicate_message(best[1]["title"], best[1]["id"], best[0])
        return None

    def _prepare_embedding(
        self, title: str, what: str, why: str | None, impact: str | None, tags: list[str]
    ) -> list[float] | None:
        """Compute an embedding before entering a database write transaction."""
        text = _embedding_text(title, what, why, impact, tags, self.c.ignore_patterns)
        try:
            return self.c.embedding_provider.embed(text)
        except Exception as exc:
            # One line per failure: an unreachable provider (e.g. Ollama not
            # running) is routine, and a traceback per save floods MCP logs.
            logger.warning("Embedding failed (%s) — memory will be saved without a vector.", exc)
            logger.debug("Embedding failure detail", exc_info=True)
            return None

    def _store_embedding(self, rowid: int, embedding: list[float]) -> None:
        """Store a precomputed embedding inside the caller's transaction."""
        if self._ensure_vectors(embedding):
            self.c.memory_repo.insert_vector(rowid, embedding)

    @staticmethod
    def _scope_dir(org: str, project: str) -> str:
        """Vault subdirectory for a memory's scope (project / @org / @global)."""
        if project:
            return project
        if org and org != GLOBAL_ORG:
            return f"@{org}"
        return "@global"

    def save(self, raw: RawMemoryInput, project: str | None = None, org: str | None = None) -> dict[str, Any]:
        """Save a memory with full pipeline: redact, write markdown, index, embed.

        ``project``/``org`` together set the scope. An empty ``project`` with an
        ``org`` is an org-level (company-wide) memory; ``org="global"`` is global.
        """
        resolved = resolve_write_scope(project, self.c.config)
        project = resolved.project
        org = org if org is not None else resolved.org
        today = date.today().isoformat()
        vault_project_dir = os.path.join(self.c.vault_dir, self._scope_dir(org, project))
        os.makedirs(vault_project_dir, exist_ok=True)

        raw_data = redact_values(raw.model_dump(), self.c.ignore_patterns)
        assert isinstance(raw_data, dict)
        raw = RawMemoryInput.model_validate(raw_data)
        warnings = self._details_warnings(raw)
        journey_id = self._resolve_journey(raw.journey_id, warnings)
        raw = raw.model_copy(update={"journey_id": journey_id})

        # Exact-title dedup, confined to the exact scope layer being written so
        # an org/global write can't merge into a project.
        existing = self.c.memory_repo.find_by_title(raw.title, project, org)
        if existing:
            return self._merge_into(existing, raw, today, warnings)

        # New memory — warn (never block) when it looks semantically close to
        # an existing one. FTS candidates back the check when embeddings are down.
        candidates: list[dict[str, Any]] = []
        try:
            if org:
                candidates = self.c.memory_repo.fts_search(
                    f"{raw.title} {raw.what}",
                    limit=5,
                    project=project,
                    org=org,
                    include_org=not project,
                    include_global=False,
                )
            else:
                candidates = self.c.memory_repo.fts_search(f"{raw.title} {raw.what}", limit=5, project=project)
        except Exception:
            logger.debug("FTS dedup search failed; treating as new memory", exc_info=True)

        embedding = self._prepare_embedding(raw.title, raw.what, raw.why, raw.impact, raw.tags)
        near_dup = self._near_duplicate_warning(raw, project, org, candidates, embedding)
        if near_dup:
            warnings.append(near_dup)

        file_path = os.path.join(vault_project_dir, f"{today}-session.md")
        mem = Memory.from_raw(raw, project=project, org=org, file_path=file_path)
        mem_dict = mem.model_dump()

        with self.c.db.transaction():
            rowid = self.c.memory_repo.insert(mem_dict, details=raw.details)
            if raw.journey_id:
                from arcane.services.journey import JourneyService

                JourneyService(self.c).link_memory(raw.journey_id, mem.id)
            if embedding is not None:
                self._store_embedding(rowid, embedding)
            write_session_memory(vault_project_dir, mem_dict, today, details=raw.details)
        logger.debug("Created memory id=%s project=%s", mem.id, project)

        return {"id": mem.id, "file_path": file_path, "action": "created", "warnings": warnings}

    def _merge_into(
        self, existing: dict[str, Any], raw: RawMemoryInput, today: str, warnings: list[str]
    ) -> dict[str, Any]:
        """Fold a same-titled save into *existing* instead of creating a duplicate."""
        existing_id = existing["id"]
        merged_tags = self._merge_tags(existing.get("tags") or [], raw.tags)
        details_append = f"--- updated {today} ---\n{raw.details}" if raw.details else None
        embedding = self._prepare_embedding(existing["title"], raw.what, raw.why, raw.impact, merged_tags)

        with self.c.db.transaction():
            self.c.memory_repo.update(
                memory_id=existing_id,
                what=raw.what,
                why=raw.why,
                impact=raw.impact,
                tags=merged_tags,
                details_append=details_append,
            )
            if embedding is not None:
                self._store_embedding(existing["rowid"], embedding)
            if raw.journey_id and not self.c.relationship_repo.exists(
                "memory", existing_id, "journey", raw.journey_id, RelationType.PART_OF.value
            ):
                from arcane.services.journey import JourneyService

                JourneyService(self.c).link_memory(raw.journey_id, existing_id)
        logger.debug("Merged duplicate memory id=%s", existing_id)

        return {
            "id": existing_id,
            "file_path": existing.get("file_path", ""),
            "action": "updated",
            "warnings": warnings,
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
        source: str | None = None,
        use_vectors: bool = True,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        if project:
            project = resolve_read_project(project, self.c.config)
        if not use_vectors:
            return hybrid_search(
                self.c.memory_repo,
                None,
                query,
                limit=limit,
                project=project,
                source=source,
                org=org,
                include_org=include_org,
                include_global=include_global,
            )

        if self.vectors_available:
            try:
                return tiered_search(
                    self.c.memory_repo,
                    self.c.embedding_provider,
                    query,
                    limit=limit,
                    project=project,
                    source=source,
                    org=org,
                    include_org=include_org,
                    include_global=include_global,
                )
            except DimensionMismatchError:
                logger.warning("Vector dimension mismatch — falling back to FTS search")
            except Exception:
                logger.debug("Vector search failed; falling back to FTS", exc_info=True)

        return tiered_search(
            self.c.memory_repo,
            None,
            query,
            limit=limit,
            project=project,
            source=source,
            org=org,
            include_org=include_org,
            include_global=include_global,
        )

    def _ollama_warm(self) -> bool:
        base_url = self.c.config.embedding.base_url or "http://localhost:11434"
        try:
            from arcane.infra.embeddings.ollama import is_model_loaded

            return is_model_loaded(self.c.config.embedding.model, base_url)
        except Exception:
            logger.debug("Could not check Ollama model status", exc_info=True)
            return False

    def _should_use_semantic(self, semantic_mode: str) -> bool:
        if semantic_mode == "never":
            return False
        if semantic_mode == "always":
            return True
        if self.c.config.embedding.provider == "ollama":
            return self._ollama_warm()
        return True

    @staticmethod
    def _apply_global_cap(results: list[dict[str, Any]], cap: int | None) -> list[dict[str, Any]]:
        """Trim global-layer (scope_rank==1) entries to ``cap``, preserving order."""
        if cap is None:
            return results
        out: list[dict[str, Any]] = []
        seen_global = 0
        for r in results:
            if r.get("scope_rank") == 1:
                if seen_global >= cap:
                    continue
                seen_global += 1
            out.append(r)
        return out

    def get_context(
        self,
        limit: int = 10,
        project: str | None = None,
        source: str | None = None,
        query: str | None = None,
        semantic_mode: str | None = None,
        topup_recent: bool | None = None,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
        global_cap: int | None = 2,
    ) -> tuple[list[dict[str, Any]], int]:
        if project:
            project = resolve_read_project(project, self.c.config)
        total = self.c.memory_repo.count(
            project=project, source=source, org=org, include_org=include_org, include_global=include_global
        )

        if semantic_mode is None:
            semantic_mode = self.c.config.context.semantic
        if semantic_mode not in {"auto", "always", "never"}:
            semantic_mode = "auto"
        if topup_recent is None:
            topup_recent = self.c.config.context.topup_recent

        results: list[dict[str, Any]]
        if query:
            use_vectors = self._should_use_semantic(semantic_mode)
            results = self.search(
                query,
                limit=limit,
                project=project,
                source=source,
                use_vectors=use_vectors,
                org=org,
                include_org=include_org,
                include_global=include_global,
            )
            if topup_recent and len(results) < limit:
                recent = self.c.memory_repo.list_recent(
                    limit=limit,
                    project=project,
                    source=source,
                    org=org,
                    include_org=include_org,
                    include_global=include_global,
                )
                seen = {r["id"] for r in results}
                for r in recent:
                    if r["id"] not in seen:
                        results.append(r)
                        if len(results) >= limit:
                            break
        else:
            results = self.c.memory_repo.list_recent(
                limit=limit,
                project=project,
                source=source,
                org=org,
                include_org=include_org,
                include_global=include_global,
            )

        if org is not None:
            results = self._apply_global_cap(results, global_cap)

        return results, total

    def update(
        self,
        memory_id: str,
        what: str | None = None,
        why: str | None = None,
        impact: str | None = None,
        tags: list[str] | None = None,
        details_append: str | None = None,
    ) -> bool:
        """Update an existing memory (by ID or prefix) and refresh its embedding."""
        full_id = self.c.memory_repo.resolve_prefix(memory_id)
        if full_id is None:
            return False

        existing = self.c.memory_repo.get(full_id)
        if not existing:
            return False
        what = redact(what, self.c.ignore_patterns) if what is not None else None
        why = redact(why, self.c.ignore_patterns) if why is not None else None
        impact = redact(impact, self.c.ignore_patterns) if impact is not None else None
        sanitized_tags = redact_values(tags, self.c.ignore_patterns) if tags is not None else None
        assert sanitized_tags is None or isinstance(sanitized_tags, list)
        tags = sanitized_tags
        details_append = redact(details_append, self.c.ignore_patterns) if details_append is not None else None
        embedding = self._prepare_embedding(
            existing["title"],
            what if what is not None else existing["what"],
            why if why is not None else existing.get("why"),
            impact if impact is not None else existing.get("impact"),
            tags if tags is not None else existing.get("tags") or [],
        )

        with self.c.db.transaction():
            updated = self.c.memory_repo.update(
                memory_id=full_id,
                what=what,
                why=why,
                impact=impact,
                tags=tags,
                details_append=details_append,
            )
            if not updated:
                return False
            rowid = self.c.memory_repo.get_rowid(full_id)
            if rowid is not None and embedding is not None:
                self._store_embedding(rowid, embedding)
        return True

    def get_details(self, memory_id: str) -> dict[str, Any] | None:
        return self.c.memory_repo.get_details(memory_id)

    def delete(self, memory_id: str) -> bool:
        full_id = self.c.memory_repo.resolve_prefix(memory_id)
        if full_id is None:
            return False
        memory = self.c.memory_repo.get(full_id)
        if memory is None:
            return False
        with self.c.db.transaction():
            deleted = self.c.memory_repo.delete(full_id)
            if deleted:
                remove_session_memory(memory["file_path"], full_id, memory["title"])
            return deleted

    def reindex(self, progress_callback: Any = None) -> dict[str, Any]:
        """Rebuild the vector index from scratch.

        Every embedding is computed before the database is touched: embedding
        is slow, and holding the write lock meanwhile would make every other
        Arcane process fail with ``database is locked``. The table is then
        dropped, recreated and filled in one short transaction, so an
        interrupted run leaves the old index intact. (A vec0 table cannot be
        swapped in with ``ALTER TABLE ... RENAME``: its shadow tables keep
        their old names and the renamed table stops working.)
        """
        memories = self.c.memory_repo.list_all_for_reindex()
        total = len(memories)
        logger.info("Reindexing %d memories with model=%s", total, self.c.config.embedding.model)

        texts = [
            _embedding_text(
                mem["title"], mem["what"], mem.get("why"), mem.get("impact"), mem["tags"], self.c.ignore_patterns
            )
            for mem in memories
        ]
        packed: list[bytes] = []
        dim: int | None = None
        for start in range(0, total, REINDEX_BATCH_SIZE):
            for embedding in self.c.embedding_provider.embed_batch(texts[start : start + REINDEX_BATCH_SIZE]):
                if dim is None:
                    dim = len(embedding)
                elif len(embedding) != dim:
                    raise ValueError(f"Embedding provider returned mixed dimensions ({dim} and {len(embedding)}).")
                packed.append(struct.pack(f"{dim}f", *embedding))
            if progress_callback:
                progress_callback(len(packed), total)
        if dim is None:
            dim = len(self.c.embedding_provider.embed("dimension probe"))

        stored_dim = self.c.memory_repo.get_embedding_dim()
        last_rowid = memories[-1]["rowid"] if memories else 0
        rows: list[tuple[int, bytes]] = [(mem["rowid"], vec) for mem, vec in zip(memories, packed)]
        with self.c.db.transaction():
            # Memories saved while the embeddings were computed already have a
            # vector in the live table; carry those over when the shape matches.
            if stored_dim == dim and self.c.memory_repo._has_vec_table():
                late = self.c.db.fetchall("SELECT rowid, embedding FROM memories_vec WHERE rowid > ?", (last_rowid,))
                rows += [(row["rowid"], row["embedding"]) for row in late]
            # Left behind by an interrupted run of the old staging-table reindex.
            self.c.db.execute("DROP TABLE IF EXISTS memories_vec_staging")
            self.c.memory_repo.drop_vec_table()
            create_vec_table(self.c.db, dim)
            self.c.db.executemany("INSERT INTO memories_vec (rowid, embedding) VALUES (?, ?)", rows)
            self.c.memory_repo.set_embedding_dim(dim)
        self.c.memory_repo.invalidate_vec_cache()

        return {"count": total, "dim": dim, "model": self.c.config.embedding.model}
