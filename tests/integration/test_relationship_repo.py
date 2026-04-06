"""Integration tests for RelationshipRepository."""

import uuid
from datetime import datetime, timezone


def make_rel(**overrides) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "source_type": "memory",
        "source_id": str(uuid.uuid4()),
        "target_type": "journey",
        "target_id": str(uuid.uuid4()),
        "relation": "part_of",
        "created_at": now,
    }
    defaults.update(overrides)
    return defaults


class TestRelationshipRepoBasic:
    def test_insert_and_get_from(self, relationship_repo):
        rel = make_rel(source_type="memory", source_id="mem-1")
        relationship_repo.insert(rel)

        results = relationship_repo.get_from("memory", "mem-1")
        assert len(results) == 1
        assert results[0]["id"] == rel["id"]

    def test_get_to(self, relationship_repo):
        rel = make_rel(target_type="journey", target_id="j-1")
        relationship_repo.insert(rel)

        results = relationship_repo.get_to("journey", "j-1")
        assert len(results) == 1

    def test_get_all_for(self, relationship_repo):
        entity_id = "mem-x"
        # outgoing
        relationship_repo.insert(make_rel(source_type="memory", source_id=entity_id))
        # incoming
        relationship_repo.insert(make_rel(target_type="memory", target_id=entity_id))

        results = relationship_repo.get_all_for("memory", entity_id)
        assert len(results) == 2

    def test_delete(self, relationship_repo):
        rel = make_rel()
        relationship_repo.insert(rel)
        assert relationship_repo.count() == 1

        deleted = relationship_repo.delete(rel["id"])
        assert deleted is True
        assert relationship_repo.count() == 0

    def test_delete_nonexistent(self, relationship_repo):
        assert relationship_repo.delete("nonexistent") is False

    def test_count(self, relationship_repo):
        assert relationship_repo.count() == 0
        relationship_repo.insert(make_rel())
        relationship_repo.insert(make_rel())
        assert relationship_repo.count() == 2


class TestRelationshipTrace:
    def test_trace_simple_chain(self, relationship_repo):
        """A -> B -> C should return both edges."""
        relationship_repo.insert(
            make_rel(
                source_type="memory",
                source_id="a",
                target_type="journey",
                target_id="b",
                relation="led_to",
            )
        )
        relationship_repo.insert(
            make_rel(
                source_type="journey",
                source_id="b",
                target_type="artifact",
                target_id="c",
                relation="resulted_in",
            )
        )

        result = relationship_repo.trace("memory", "a", max_depth=5)
        assert len(result) == 2

    def test_trace_max_depth_0(self, relationship_repo):
        """Depth 0 should only return direct edges."""
        relationship_repo.insert(
            make_rel(
                source_type="memory",
                source_id="a",
                target_type="journey",
                target_id="b",
            )
        )
        relationship_repo.insert(
            make_rel(
                source_type="journey",
                source_id="b",
                target_type="artifact",
                target_id="c",
            )
        )

        result = relationship_repo.trace("memory", "a", max_depth=0)
        assert len(result) == 1

    def test_trace_handles_cycle(self, relationship_repo):
        """Graph with a cycle should not loop infinitely."""
        relationship_repo.insert(
            make_rel(
                source_type="memory",
                source_id="a",
                target_type="memory",
                target_id="b",
            )
        )
        relationship_repo.insert(
            make_rel(
                source_type="memory",
                source_id="b",
                target_type="memory",
                target_id="a",
            )
        )

        result = relationship_repo.trace("memory", "a", max_depth=10)
        assert len(result) == 2
