"""Service container — dependency injection wiring."""

from __future__ import annotations

import os
from dataclasses import dataclass

from arcane.infra.config import ArcaneConfig, get_home, load_config
from arcane.infra.db.artifact_repo import ArtifactRepository
from arcane.infra.db.connection import Database
from arcane.infra.db.insight_repo import InsightRepository
from arcane.infra.db.journey_repo import JourneyRepository
from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.db.relationship_repo import RelationshipRepository
from arcane.infra.db.schema import create_schema
from arcane.infra.embeddings.base import EmbeddingProvider
from arcane.infra.redaction import load_memoryignore


@dataclass
class ServiceContainer:
    """Holds all repositories and shared resources."""

    db: Database
    config: ArcaneConfig
    home: str
    vault_dir: str

    # Repositories
    memory_repo: MemoryRepository
    journey_repo: JourneyRepository
    artifact_repo: ArtifactRepository
    relationship_repo: RelationshipRepository
    insight_repo: InsightRepository

    # Lazy
    _embedding_provider: EmbeddingProvider | None = None
    _ignore_patterns: list[str] | None = None

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = _create_embedding_provider(self.config)
        return self._embedding_provider

    @property
    def ignore_patterns(self) -> list[str]:
        if self._ignore_patterns is None:
            self._ignore_patterns = load_memoryignore(
                os.path.join(self.home, ".memoryignore")
            )
        return self._ignore_patterns

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ServiceContainer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_container(home: str | None = None) -> ServiceContainer:
    """Create a fully wired service container."""
    home = home or get_home()
    vault_dir = os.path.join(home, "vault")
    db_path = os.path.join(home, "index.db")
    config_path = os.path.join(home, "config.yaml")

    os.makedirs(vault_dir, exist_ok=True)

    config = load_config(config_path)
    db = Database(db_path)
    create_schema(db)

    return ServiceContainer(
        db=db,
        config=config,
        home=home,
        vault_dir=vault_dir,
        memory_repo=MemoryRepository(db),
        journey_repo=JourneyRepository(db),
        artifact_repo=ArtifactRepository(db),
        relationship_repo=RelationshipRepository(db),
        insight_repo=InsightRepository(db),
    )


def _create_embedding_provider(config: ArcaneConfig) -> EmbeddingProvider:
    provider = config.embedding.provider
    if provider == "ollama":
        from arcane.infra.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model=config.embedding.model,
            base_url=config.embedding.base_url or "http://localhost:11434",
        )
    elif provider == "openai":
        from arcane.infra.embeddings.openai_embed import OpenAIEmbedding

        return OpenAIEmbedding(
            model=config.embedding.model,
            api_key=config.embedding.api_key,
        )
    raise ValueError(f"Unknown embedding provider: {provider}")
