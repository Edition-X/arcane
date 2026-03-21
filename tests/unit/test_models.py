"""Unit tests for domain models."""

import pytest
from pydantic import ValidationError

from arcane.domain.enums import (
    ArtifactType,
    Category,
    JourneyStatus,
    RelationType,
    Severity,
)
from arcane.domain.models import (
    Artifact,
    Insight,
    Journey,
    Memory,
    MemoryDetail,
    RawMemoryInput,
    Relationship,
    SearchResult,
)


class TestRawMemoryInput:
    def test_minimal(self):
        raw = RawMemoryInput(title="Test", what="Something")
        assert raw.title == "Test"
        assert raw.what == "Something"
        assert raw.tags == []
        assert raw.category is None

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            RawMemoryInput(title="x" * 61, what="test")

    def test_valid_category_passes(self):
        raw = RawMemoryInput(title="Test", what="x", category="decision")
        assert raw.category == "decision"

    def test_invalid_category_falls_back_to_context(self):
        raw = RawMemoryInput(title="Test", what="x", category="nonsense")
        assert raw.category == "context"

    def test_none_category_stays_none(self):
        raw = RawMemoryInput(title="Test", what="x", category=None)
        assert raw.category is None

    def test_journey_id(self):
        raw = RawMemoryInput(title="Test", what="x", journey_id="abc-123")
        assert raw.journey_id == "abc-123"


class TestMemory:
    def test_defaults(self):
        m = Memory(title="T", what="W", project="p")
        assert m.id  # auto-generated
        assert m.created_at
        assert m.updated_count == 0
        assert m.metadata == {}

    def test_from_raw(self):
        raw = RawMemoryInput(
            title="My Decision",
            what="We chose X",
            why="Because Y",
            tags=["infra"],
            category="decision",
            journey_id="j-1",
        )
        mem = Memory.from_raw(raw, project="arcane", file_path="/tmp/test.md")
        assert mem.title == "My Decision"
        assert mem.project == "arcane"
        assert mem.section_anchor == "my-decision"
        assert mem.metadata == {"journey_id": "j-1"}

    def test_from_raw_no_journey(self):
        raw = RawMemoryInput(title="T", what="W")
        mem = Memory.from_raw(raw, project="p")
        assert mem.metadata == {}


class TestJourney:
    def test_defaults(self):
        j = Journey(title="Test Journey")
        assert j.status == JourneyStatus.ACTIVE
        assert j.completed_at is None


class TestArtifact:
    def test_creation(self):
        a = Artifact(
            artifact_type=ArtifactType.PR,
            external_id="42",
            title="Fix bug",
            project="test",
        )
        assert a.artifact_type == "pr"
        assert a.raw_data == {}


class TestRelationship:
    def test_creation(self):
        r = Relationship(
            source_type="memory",
            source_id="m-1",
            target_type="journey",
            target_id="j-1",
            relation=RelationType.PART_OF,
        )
        assert r.relation == "part_of"


class TestInsight:
    def test_defaults(self):
        i = Insight(
            insight_type="ci_flake",
            title="Flaky test",
            body="Details here",
            project="test",
        )
        assert i.severity == Severity.INFO
        assert i.acknowledged is False


class TestSearchResult:
    def test_defaults(self):
        sr = SearchResult(id="x", title="T", what="W")
        assert sr.score == 0.0
        assert sr.has_details is False


class TestEnums:
    def test_category_values(self):
        assert "decision" in [c.value for c in Category]
        assert "poc" in [c.value for c in Category]

    def test_relation_type_values(self):
        assert "led_to" in [r.value for r in RelationType]
        assert "part_of" in [r.value for r in RelationType]

    def test_journey_status(self):
        assert JourneyStatus.ACTIVE == "active"
        assert JourneyStatus.COMPLETED == "completed"
