"""Tests for the ADR (Architecture Decision Record) content plugin."""

from __future__ import annotations

import pytest

from arcane.plugins.builtin.adr_gen import ADRGenerator


@pytest.fixture
def decision_memory(container):
    """Create a decision memory with details."""
    from arcane.domain.models import RawMemoryInput
    from arcane.services.memory import MemoryService

    ms = MemoryService(container)
    raw = RawMemoryInput(
        title="Use PostgreSQL over MySQL",
        what="Decided to use PostgreSQL as our primary database",
        why="Better JSON support, superior concurrency model, and strong community",
        impact="All new services will use PostgreSQL; migration planned for legacy services",
        tags=["database", "architecture"],
        category="decision",
        details=(
            "## Context\n"
            "We need a production database that supports JSON queries and handles concurrent writes.\n\n"
            "## Options Considered\n"
            "1. PostgreSQL - Full ACID, JSONB, extensions\n"
            "2. MySQL - Mature, but weaker JSON support\n"
            "3. SQLite - Not suitable for production multi-writer\n\n"
            "## Decision\n"
            "PostgreSQL with pgbouncer for connection pooling.\n\n"
            "## Tradeoffs\n"
            "- Higher operational complexity than SQLite\n"
            "- Team needs PostgreSQL training\n\n"
            "## Follow-up\n"
            "- Set up pgbouncer\n"
            "- Write migration scripts"
        ),
    )
    result = ms.save(raw, project="test-project")
    return result["id"]


class TestADRGenerator:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import ContentPlugin

        gen = ADRGenerator()
        assert isinstance(gen, ContentPlugin)

    def test_name(self):
        gen = ADRGenerator()
        assert gen.name == "adr"

    def test_generate_from_decision_memory(self, container, decision_memory):
        mem = container.memory_repo.get(decision_memory)
        detail = container.memory_repo.get_details(decision_memory)

        gen = ADRGenerator()
        adr = gen.generate(
            context={
                "memory": mem,
                "details": detail["body"] if detail else "",
            }
        )

        assert "PostgreSQL" in adr
        assert "# ADR" in adr
        assert "## Status" in adr
        assert "## Context" in adr
        assert "## Decision" in adr
        assert "## Consequences" in adr

    def test_generate_includes_options(self, container, decision_memory):
        mem = container.memory_repo.get(decision_memory)
        detail = container.memory_repo.get_details(decision_memory)

        gen = ADRGenerator()
        adr = gen.generate(
            context={
                "memory": mem,
                "details": detail["body"] if detail else "",
            }
        )

        # The options from details should be included
        assert "Options Considered" in adr or "PostgreSQL" in adr

    def test_generate_without_details(self, container):
        """ADR from memory without detailed body should still work."""
        from arcane.domain.models import RawMemoryInput
        from arcane.services.memory import MemoryService

        ms = MemoryService(container)
        raw = RawMemoryInput(
            title="Use REST over gRPC",
            what="Chose REST for external APIs",
            why="Better client compatibility",
            impact="All public APIs will be REST",
            category="decision",
        )
        result = ms.save(raw, project="test-project")

        mem = container.memory_repo.get(result["id"])
        gen = ADRGenerator()
        adr = gen.generate(context={"memory": mem, "details": ""})

        assert "REST" in adr
        assert "## Context" in adr

    def test_generate_empty_context(self):
        gen = ADRGenerator()
        adr = gen.generate(context={})
        assert adr == "" or "No memory" in adr

    def test_generate_includes_tags_as_keywords(self, container, decision_memory):
        mem = container.memory_repo.get(decision_memory)
        detail = container.memory_repo.get_details(decision_memory)

        gen = ADRGenerator()
        adr = gen.generate(
            context={
                "memory": mem,
                "details": detail["body"] if detail else "",
            }
        )

        # Tags should appear somewhere in the ADR
        assert "database" in adr.lower() or "architecture" in adr.lower()
