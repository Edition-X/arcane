"""Shared fixtures for all Arcane tests."""

from __future__ import annotations

import os
import tempfile

import pytest

from arcane.infra.config import ArcaneConfig, ContextConfig, EmbeddingConfig
from arcane.infra.db.artifact_repo import ArtifactRepository
from arcane.infra.db.connection import Database
from arcane.infra.db.insight_repo import InsightRepository
from arcane.infra.db.journey_repo import JourneyRepository
from arcane.infra.db.memory_repo import MemoryRepository
from arcane.infra.db.relationship_repo import RelationshipRepository
from arcane.infra.db.schema import create_schema
from arcane.infra.embeddings.base import EmbeddingProvider
from arcane.services.container import ServiceContainer


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for tests — returns hash-based vectors."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.call_count = 0

    def embed(self, text: str) -> list[float]:
        self.call_count += 1
        h = hash(text) & 0xFFFFFFFF
        return [(((h * (i + 1)) % 1000) / 1000.0) for i in range(self.dim)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture
def db():
    """In-memory Database with schema created."""
    database = Database(":memory:")
    create_schema(database)
    yield database
    database.close()


@pytest.fixture
def tmp_home(tmp_path):
    """Temporary arcane home directory with vault subdir."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return str(tmp_path)


@pytest.fixture
def config():
    """Default ArcaneConfig for tests."""
    return ArcaneConfig(
        embedding=EmbeddingConfig(provider="ollama", model="test-model"),
        context=ContextConfig(semantic="never", topup_recent=True),
    )


@pytest.fixture
def fake_embedder():
    """FakeEmbeddingProvider with 64 dimensions."""
    return FakeEmbeddingProvider(dim=64)


@pytest.fixture
def container(db, tmp_home, config, fake_embedder):
    """Fully wired ServiceContainer with in-memory DB and fake embedder."""
    c = ServiceContainer(
        db=db,
        config=config,
        home=tmp_home,
        vault_dir=os.path.join(tmp_home, "vault"),
        memory_repo=MemoryRepository(db),
        journey_repo=JourneyRepository(db),
        artifact_repo=ArtifactRepository(db),
        relationship_repo=RelationshipRepository(db),
        insight_repo=InsightRepository(db),
        _embedding_provider=fake_embedder,
        _ignore_patterns=[],
    )
    return c


@pytest.fixture
def memory_repo(db):
    return MemoryRepository(db)


@pytest.fixture
def journey_repo(db):
    return JourneyRepository(db)


@pytest.fixture
def relationship_repo(db):
    return RelationshipRepository(db)


@pytest.fixture
def artifact_repo(db):
    return ArtifactRepository(db)


@pytest.fixture
def insight_repo(db):
    return InsightRepository(db)


def make_memory_dict(**overrides) -> dict:
    """Helper to create a minimal valid memory dict."""
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "title": "Test Memory",
        "what": "Something happened.",
        "why": None,
        "impact": None,
        "tags": [],
        "category": "context",
        "project": "test-project",
        "source": None,
        "related_files": [],
        "file_path": "/tmp/test.md",
        "section_anchor": "test-memory",
        "created_at": now,
        "updated_at": now,
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults
