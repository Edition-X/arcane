"""Integration tests for safe entity mutation and deletion."""

from __future__ import annotations

import json

import pytest

from arcane.domain.enums import RelationType
from arcane.domain.models import RawMemoryInput, Relationship
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.mcp_server.tools.memory_tools import handle_delete
from arcane.services.memory import MemoryService
from tests.conftest import make_memory_dict
from tests.integration.test_journey_repo import make_journey


def test_ambiguous_memory_prefix_is_rejected_without_mutation(container):
    container.memory_repo.insert(make_memory_dict(id="12345678-a", title="First", what="First memory"))
    container.memory_repo.insert(make_memory_dict(id="12345678-b", title="Second", what="Second memory"))

    with pytest.raises(IdentifierResolutionError, match="ambiguous"):
        MemoryService(container).delete("12345678")

    assert container.memory_repo.count() == 2
    result = json.loads(handle_delete(MemoryService(container), "12345678"))
    assert "ambiguous" in result["error"]


@pytest.mark.parametrize("value", ["", "%", "abc"])
def test_invalid_memory_prefix_is_rejected(value, container):
    with pytest.raises(IdentifierResolutionError):
        MemoryService(container).delete(value)


def test_ambiguous_journey_and_insight_prefixes_are_rejected(container):
    container.journey_repo.insert(make_journey(id="12345678-a"))
    container.journey_repo.insert(make_journey(id="12345678-b"))
    with pytest.raises(IdentifierResolutionError, match="ambiguous"):
        container.journey_repo.update("12345678", summary="Must not update")

    insight = {
        "id": "12345678-c",
        "insight_type": "health",
        "title": "First insight",
        "body": "Body",
        "project": "test",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    second_insight = {**insight, "id": "12345678-d", "title": "Second insight"}
    container.insight_repo.insert(insight)
    container.insight_repo.insert(second_insight)
    with pytest.raises(IdentifierResolutionError, match="ambiguous"):
        container.insight_repo.acknowledge("12345678")


def test_memory_delete_removes_all_persisted_representations(container):
    service = MemoryService(container)
    saved = service.save(
        RawMemoryInput(title="Disposable memory", what="unique deletion token", details="Delete me"),
        project="test-project",
    )
    memory_id = saved["id"]
    rowid = container.memory_repo.get_rowid(memory_id)
    container.relationship_repo.insert(
        Relationship(
            source_type="memory",
            source_id=memory_id,
            target_type="memory",
            target_id="other-memory",
            relation=RelationType.REFERENCES,
        ).model_dump()
    )

    assert service.delete(memory_id) is True

    assert container.memory_repo.get(memory_id) is None
    assert container.memory_repo.get_details(memory_id) is None
    assert container.memory_repo.fts_search("unique deletion token") == []
    assert container.relationship_repo.get_all_for("memory", memory_id) == []
    assert rowid is not None
    assert container.db.fetchone("SELECT rowid FROM memories_vec WHERE rowid = ?", (rowid,)) is None
    assert "Disposable memory" not in open(saved["file_path"]).read()
