"""MemoryService — orchestrates memory operations."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

from arcane.domain.models import Memory, RawMemoryInput
from arcane.infra.db.schema import create_vec_table
from arcane.infra.markdown import write_session_memory
from arcane.infra.redaction import redact
from arcane.infra.search import hybrid_search, tiered_search
from arcane.services.container import ServiceContainer

logger = logging.getLogger(__name__)


class DimensionMismatchError(Exception):
    def __init__(self, stored_dim: int, new_dim: int):
        self.stored_dim = stored_dim
        self.new_dim = new_dim
        super().__init__(
            f"Embedding dimension mismatch: database has {stored_dim}, "
            f"provider returned {new_dim}. Run 'arcane reindex' to rebuild."
        )


def _embedding_text(title: str, what: str, why: str | None, impact: str | None, tags: list[str]) -> str:
    """Build the text string that is fed to the embedding model."""
    return f"{title} {what} {why or ''} {impact or ''} {' '.join(tags)}"


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
                "Embedding dimension mismatch: DB has %d, provider returned %d. "
                "Run 'arcane reindex' to rebuild.",
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

    def _embed_and_store(self, rowid: int, title: str, what: str, why: str | None, impact: str | None, tags: list[str]) -> None:
        """Compute embedding and upsert into the vector table.  Logs on failure."""
        text = _embedding_text(title, what, why, impact, tags)
        try:
            embedding = self.c.embedding_provider.embed(text)
        except Exception:
            logger.warning("Embedding failed for rowid=%d — memory saved without vector.", rowid, exc_info=True)
            return
        if self._ensure_vectors(embedding):
            self.c.memory_repo.insert_vector(rowid, embedding)

    def save(self, raw: RawMemoryInput, project: str | None = None) -> dict[str, Any]:
        """Save a memory with full pipeline: redact, write markdown, index, embed."""
        project = project or os.path.basename(os.getcwd())
        today = date.today().isoformat()
        vault_project_dir = os.path.join(self.c.vault_dir, project)
        os.makedirs(vault_project_dir, exist_ok=True)

        warnings = self._details_warnings(raw)

        # Redact before any persistence
        raw.what = redact(raw.what, self.c.ignore_patterns)
        if raw.why:
            raw.why = redact(raw.why, self.c.ignore_patterns)
        if raw.impact:
            raw.impact = redact(raw.impact, self.c.ignore_patterns)
        if raw.details:
            raw.details = redact(raw.details, self.c.ignore_patterns)

        # Dedup check — FTS search by title + what
        candidates: list[dict[str, Any]] = []
        try:
            candidates = self.c.memory_repo.fts_search(
                f"{raw.title} {raw.what}", limit=5, project=project
            )
        except Exception:
            logger.debug("FTS dedup search failed; treating as new memory", exc_info=True)

        if candidates:
            # Widen the pool to compute a stable normalisation baseline
            broad = candidates
            if len(broad) == 1:
                try:
                    broad = self.c.memory_repo.fts_search(f"{raw.title} {raw.what}", limit=5) or broad
                except Exception:
                    logger.debug("Broadened dedup search failed; using narrow pool", exc_info=True)

            max_score = max(c["score"] for c in broad) if broad else 0.0
            top = candidates[0]
            normalized = top["score"] / max_score if max_score > 0 else 0.0
            title_match = raw.title.strip().lower() == top["title"].strip().lower()

            if normalized >= 0.7 and title_match:
                existing_id = top["id"]
                merged_tags = self._merge_tags(top.get("tags") or [], raw.tags)
                details_append = f"--- updated {today} ---\n{raw.details}" if raw.details else None

                self.c.memory_repo.update(
                    memory_id=existing_id,
                    what=raw.what,
                    why=raw.why,
                    impact=raw.impact,
                    tags=merged_tags,
                    details_append=details_append,
                )
                logger.debug("Merged duplicate memory id=%s", existing_id)

                rowid = self.c.memory_repo.get_rowid(existing_id)
                if rowid is not None:
                    self._embed_and_store(rowid, top["title"], raw.what, raw.why, raw.impact, merged_tags)

                return {
                    "id": existing_id,
                    "file_path": top.get("file_path", ""),
                    "action": "updated",
                    "warnings": warnings,
                }

        # New memory
        file_path = os.path.join(vault_project_dir, f"{today}-session.md")
        mem = Memory.from_raw(raw, project=project, file_path=file_path)
        mem_dict = mem.model_dump()

        write_session_memory(vault_project_dir, mem_dict, today, details=raw.details)
        rowid = self.c.memory_repo.insert(mem_dict, details=raw.details)
        logger.debug("Created memory id=%s project=%s", mem.id, project)

        if raw.journey_id:
            from arcane.services.journey import JourneyService
            JourneyService(self.c).link_memory(raw.journey_id, mem.id)

        self._embed_and_store(rowid, mem.title, mem.what, mem.why, mem.impact, mem.tags)

        return {"id": mem.id, "file_path": file_path, "action": "created", "warnings": warnings}

    def search(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
        source: str | None = None,
        use_vectors: bool = True,
    ) -> list[dict[str, Any]]:
        if not use_vectors:
            return hybrid_search(
                self.c.memory_repo, None, query, limit=limit, project=project, source=source
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
                )
            except DimensionMismatchError:
                logger.warning("Vector dimension mismatch — falling back to FTS search")
            except Exception:
                logger.debug("Vector search failed; falling back to FTS", exc_info=True)

        return tiered_search(
            self.c.memory_repo, None, query, limit=limit, project=project, source=source
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

    def get_context(
        self,
        limit: int = 10,
        project: str | None = None,
        source: str | None = None,
        query: str | None = None,
        semantic_mode: str | None = None,
        topup_recent: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        total = self.c.memory_repo.count(project=project, source=source)

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
                query, limit=limit, project=project, source=source, use_vectors=use_vectors
            )
            if topup_recent and len(results) < limit:
                recent = self.c.memory_repo.list_recent(limit=limit, project=project, source=source)
                seen = {r["id"] for r in results}
                for r in recent:
                    if r["id"] not in seen:
                        results.append(r)
                        if len(results) >= limit:
                            break
        else:
            results = self.c.memory_repo.list_recent(limit=limit, project=project, source=source)

        return results, total

    def get_details(self, memory_id: str) -> dict[str, Any] | None:
        return self.c.memory_repo.get_details(memory_id)

    def delete(self, memory_id: str) -> bool:
        return self.c.memory_repo.delete(memory_id)

    def reindex(self, progress_callback: Any = None) -> dict[str, Any]:
        """Rebuild the vector index from scratch using a crash-safe strategy.

        All embeddings are written to a *staging* virtual table first.  Only
        when every row has been embedded successfully is the staging table
        atomically swapped into place, making the operation resumable and
        safe to interrupt.
        """
        probe = self.c.embedding_provider.embed("dimension probe")
        dim = len(probe)

        memories = self.c.memory_repo.list_all_for_reindex()
        total = len(memories)
        logger.info("Reindexing %d memories with dim=%d model=%s", total, dim, self.c.config.embedding.model)

        # Build into a staging table so interruptions don't leave the live
        # table in a half-populated state.
        self.c.db.execute("DROP TABLE IF EXISTS memories_vec_staging")
        self.c.db.execute(f"""
            CREATE VIRTUAL TABLE memories_vec_staging USING vec0(
                rowid INTEGER PRIMARY KEY,
                embedding float[{dim}]
            )
        """)

        import struct
        for i, mem in enumerate(memories):
            tags = mem.get("tags") or []  # already deserialized by _process_row
            text = _embedding_text(mem["title"], mem["what"], mem.get("why"), mem.get("impact"), tags)
            embedding = self.c.embedding_provider.embed(text)
            vec_bytes = struct.pack(f"{dim}f", *embedding)
            self.c.db.execute(
                "INSERT INTO memories_vec_staging (rowid, embedding) VALUES (?, ?)",
                (mem["rowid"], vec_bytes),
            )

            if progress_callback:
                progress_callback(i + 1, total)

        # Atomic swap: drop live table, rename staging → live.
        self.c.db.execute("DROP TABLE IF EXISTS memories_vec")
        self.c.db.execute("ALTER TABLE memories_vec_staging RENAME TO memories_vec")
        self.c.memory_repo.set_embedding_dim(dim)
        self.c.db.commit()
        self.c.memory_repo.invalidate_vec_cache()

        return {"count": total, "dim": dim, "model": self.c.config.embedding.model}
