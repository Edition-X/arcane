"""MemoryService — orchestrates memory operations."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from typing import Any

from arcane.domain.models import Memory, RawMemoryInput
from arcane.infra.db.schema import create_vec_table
from arcane.infra.markdown import write_session_memory
from arcane.infra.redaction import redact
from arcane.infra.search import hybrid_search, tiered_search
from arcane.services.container import ServiceContainer


class DimensionMismatchError(Exception):
    def __init__(self, stored_dim: int, new_dim: int):
        self.stored_dim = stored_dim
        self.new_dim = new_dim
        super().__init__(
            f"Embedding dimension mismatch: database has {stored_dim}, "
            f"provider returned {new_dim}. Run 'arcane reindex' to rebuild."
        )


class MemoryService:
    """Main orchestrator for memory operations."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container
        self._vectors_available: bool | None = None

    @property
    def vectors_available(self) -> bool:
        if self._vectors_available is None:
            self._vectors_available = self.c.memory_repo._has_vec_table()
        return self._vectors_available

    def _ensure_vectors(self, embedding: list[float]) -> bool:
        dim = len(embedding)
        stored_dim = self.c.memory_repo.get_embedding_dim()
        if stored_dim is None:
            self.c.memory_repo.set_embedding_dim(dim)
            create_vec_table(self.c.db, dim)
            self._vectors_available = True
            return True
        elif stored_dim != dim:
            self._vectors_available = False
            return False
        if not self.c.memory_repo._has_vec_table():
            create_vec_table(self.c.db, dim)
        self._vectors_available = True
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
        warnings: list[str] = []
        details = (raw.details or "").strip()
        category = (raw.category or "").strip().lower()

        if category in {"decision", "bug"} and not details:
            warnings.append(
                f"'{category}' memories should include details. "
                "Capture context, options considered, decision, tradeoffs, and follow-up."
            )
            return warnings

        if not details:
            return warnings

        if len(details) < 120:
            warnings.append(
                f"Details are brief ({len(details)} chars). Aim for at least 120 chars."
            )

        required = ["context", "options considered", "decision", "tradeoffs", "follow-up"]
        details_lc = details.lower()
        missing = [s for s in required if s not in details_lc]
        if missing:
            warnings.append("Details missing recommended sections: " + ", ".join(missing) + ".")

        return warnings

    def save(self, raw: RawMemoryInput, project: str | None = None) -> dict[str, Any]:
        """Save a memory with full pipeline: redact, write markdown, index, embed."""
        project = project or os.path.basename(os.getcwd())
        today = date.today().isoformat()
        vault_project_dir = os.path.join(self.c.vault_dir, project)
        os.makedirs(vault_project_dir, exist_ok=True)

        warnings = self._details_warnings(raw)

        # Redact
        raw.what = redact(raw.what, self.c.ignore_patterns)
        if raw.why:
            raw.why = redact(raw.why, self.c.ignore_patterns)
        if raw.impact:
            raw.impact = redact(raw.impact, self.c.ignore_patterns)
        if raw.details:
            raw.details = redact(raw.details, self.c.ignore_patterns)

        # Dedup check
        try:
            candidates = self.c.memory_repo.fts_search(
                f"{raw.title} {raw.what}", limit=5, project=project
            )
        except Exception:
            candidates = []

        if candidates:
            broad = candidates
            if len(broad) == 1:
                try:
                    broad = self.c.memory_repo.fts_search(
                        f"{raw.title} {raw.what}", limit=5
                    ) or broad
                except Exception:
                    pass
            max_score = max(c["score"] for c in broad) if broad else 0.0
            top = candidates[0]
            normalized = top["score"] / max_score if max_score > 0 else 0.0
            title_match = raw.title.strip().lower() == top["title"].strip().lower()

            if normalized >= 0.7 and title_match:
                existing_id = top["id"]
                merged_tags = self._merge_tags(
                    json.loads(top["tags"]) if isinstance(top["tags"], str) else (top["tags"] or []),
                    raw.tags,
                )
                details_append = None
                if raw.details:
                    details_append = f"--- updated {today} ---\n{raw.details}"

                self.c.memory_repo.update(
                    memory_id=existing_id,
                    what=raw.what,
                    why=raw.why,
                    impact=raw.impact,
                    tags=merged_tags,
                    details_append=details_append,
                )

                # Re-embed
                try:
                    embed_text = f"{top['title']} {raw.what} {raw.why or ''} {raw.impact or ''} {' '.join(merged_tags)}"
                    embedding = self.c.embedding_provider.embed(embed_text)
                    if self._ensure_vectors(embedding):
                        row = self.c.db.fetchone(
                            "SELECT rowid FROM memories WHERE id = ?", (existing_id,)
                        )
                        if row:
                            self.c.memory_repo.insert_vector(row["rowid"], embedding)
                except Exception:
                    pass

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

        # Auto-link to journey if specified
        if raw.journey_id:
            from arcane.services.journey import JourneyService

            js = JourneyService(self.c)
            js.link_memory(raw.journey_id, mem.id)

        # Embed
        embed_text = f"{mem.title} {mem.what} {mem.why or ''} {mem.impact or ''} {' '.join(mem.tags)}"
        try:
            embedding = self.c.embedding_provider.embed(embed_text)
            if self._ensure_vectors(embedding):
                self.c.memory_repo.insert_vector(rowid, embedding)
            else:
                print(
                    "Warning: vector dimension mismatch. Run 'arcane reindex' to rebuild.",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"Warning: embedding failed ({e}). Memory saved without vector.", file=sys.stderr)

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
                self._vectors_available = False
            except Exception:
                pass

        return tiered_search(
            self.c.memory_repo, None, query, limit=limit, project=project, source=source
        )

    def _ollama_warm(self) -> bool:
        base_url = self.c.config.embedding.base_url or "http://localhost:11434"
        try:
            from arcane.infra.embeddings.ollama import is_model_loaded
        except Exception:
            return False
        return is_model_loaded(self.c.config.embedding.model, base_url)

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
        probe = self.c.embedding_provider.embed("dimension probe")
        dim = len(probe)

        self.c.memory_repo.drop_vec_table()
        self.c.memory_repo.set_embedding_dim(dim)
        create_vec_table(self.c.db, dim)

        memories = self.c.memory_repo.list_all_for_reindex()
        total = len(memories)

        for i, mem in enumerate(memories):
            tags = ""
            if mem["tags"]:
                try:
                    tags = " ".join(json.loads(mem["tags"]))
                except (json.JSONDecodeError, TypeError):
                    tags = str(mem["tags"])

            embed_text = f"{mem['title']} {mem['what']} {mem['why'] or ''} {mem['impact'] or ''} {tags}"
            embedding = self.c.embedding_provider.embed(embed_text)
            self.c.memory_repo.insert_vector(mem["rowid"], embedding)

            if progress_callback:
                progress_callback(i + 1, total)

        self._vectors_available = True
        return {"count": total, "dim": dim, "model": self.c.config.embedding.model}
