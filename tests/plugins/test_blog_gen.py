"""Tests for the blog brief content plugin."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from arcane.plugins.builtin.blog_gen import BlogGenerator


@pytest.fixture
def journey_with_memories(container):
    """Create a journey with linked memories and artifacts."""
    from arcane.services.journey import JourneyService
    from arcane.services.memory import MemoryService
    from arcane.domain.models import RawMemoryInput, Relationship, Artifact
    from arcane.domain.enums import RelationType, ArtifactType

    js = JourneyService(container)
    ms = MemoryService(container)

    # Start journey
    result = js.start(title="Migrate to PostgreSQL", project="test-project")
    journey_id = result["id"]

    # Save memories linked to journey
    raw1 = RawMemoryInput(
        title="Evaluated DB options",
        what="Compared PostgreSQL vs MySQL vs SQLite for production workload",
        why="Need ACID compliance and better concurrency",
        impact="Narrowed down to PostgreSQL",
        tags=["database", "migration"],
        category="decision",
        journey_id=journey_id,
    )
    ms.save(raw1, project="test-project")

    raw2 = RawMemoryInput(
        title="POC: pgbouncer connection pooling",
        what="Tested pgbouncer in front of PostgreSQL under load",
        why="Concerned about connection limits in production",
        impact="pgbouncer handles 500 concurrent connections smoothly",
        tags=["database", "poc"],
        category="poc",
        journey_id=journey_id,
    )
    ms.save(raw2, project="test-project")

    # Add an artifact
    art = Artifact(
        artifact_type=ArtifactType.PR,
        external_id="PR-42",
        title="feat: PostgreSQL migration",
        url="https://github.com/org/repo/pull/42",
        project="test-project",
    )
    container.artifact_repo.insert(art.model_dump())

    # Link artifact to journey
    rel = Relationship(
        source_type="artifact", source_id=art.id,
        target_type="journey", target_id=journey_id,
        relation=RelationType.RESULTED_IN,
    )
    container.relationship_repo.insert(rel.model_dump())

    # Complete journey
    js.complete(journey_id, summary="Migrated from SQLite to PostgreSQL with pgbouncer pooling.")

    return journey_id


class TestBlogGenerator:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import ContentPlugin
        gen = BlogGenerator()
        assert isinstance(gen, ContentPlugin)

    def test_name(self):
        gen = BlogGenerator()
        assert gen.name == "blog"

    def test_generate_from_journey_context(self, container, journey_with_memories):
        """Generate a structured blog brief from a journey context."""
        from arcane.services.journey import JourneyService
        js = JourneyService(container)
        journey_data = js.show(journey_with_memories)

        gen = BlogGenerator()
        brief = gen.generate(context={"journey": journey_data})

        assert "Migrate to PostgreSQL" in brief
        assert "## Summary" in brief or "## Decision Timeline" in brief
        assert "Evaluated DB options" in brief
        assert "POC: pgbouncer" in brief

    def test_generate_includes_artifacts(self, container, journey_with_memories):
        from arcane.services.journey import JourneyService
        js = JourneyService(container)
        journey_data = js.show(journey_with_memories)

        gen = BlogGenerator()
        brief = gen.generate(context={"journey": journey_data})

        assert "PR-42" in brief or "PostgreSQL migration" in brief

    def test_generate_has_structure(self, container, journey_with_memories):
        from arcane.services.journey import JourneyService
        js = JourneyService(container)
        journey_data = js.show(journey_with_memories)

        gen = BlogGenerator()
        brief = gen.generate(context={"journey": journey_data})

        # Should have markdown structure
        assert brief.startswith("#")
        # Should have multiple sections
        assert brief.count("##") >= 2

    def test_generate_empty_context(self):
        gen = BlogGenerator()
        brief = gen.generate(context={})
        assert brief == "" or "No journey" in brief

    def test_generate_with_project_memories_only(self, container):
        """Generate a brief from project memories without a journey."""
        from arcane.services.memory import MemoryService
        from arcane.domain.models import RawMemoryInput

        ms = MemoryService(container)
        for i in range(3):
            raw = RawMemoryInput(
                title=f"Learning {i}",
                what=f"Discovered thing {i}",
                category="learning",
            )
            ms.save(raw, project="test-project")

        memories = container.memory_repo.list_recent(limit=10, project="test-project")
        gen = BlogGenerator()
        brief = gen.generate(context={"memories": memories, "project": "test-project"})

        assert "test-project" in brief or "Learning" in brief
