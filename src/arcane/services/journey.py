"""JourneyService — orchestrates decision journey operations."""

from __future__ import annotations

import os
from typing import Any

from arcane.domain.enums import RelationType
from arcane.domain.models import Journey, Relationship
from arcane.services.container import ServiceContainer


class JourneyService:
    """Manages decision journeys and their relationships."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def start(
        self,
        title: str,
        project: str | None = None,
        linear_issue_id: str | None = None,
    ) -> dict[str, Any]:
        project = project or os.path.basename(os.getcwd())
        journey = Journey(title=title, project=project, linear_issue_id=linear_issue_id)
        self.c.journey_repo.insert(journey.model_dump())
        return {"id": journey.id, "title": journey.title, "project": journey.project}

    def update(self, journey_id: str, summary: str | None = None, **fields: Any) -> bool:
        if summary:
            fields["summary"] = summary
        return self.c.journey_repo.update(journey_id, **fields)

    def complete(self, journey_id: str, summary: str | None = None) -> bool:
        return self.c.journey_repo.complete(journey_id, summary=summary)

    def get(self, journey_id: str) -> dict[str, Any] | None:
        return self.c.journey_repo.get(journey_id)

    def list(
        self,
        project: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.c.journey_repo.list_all(project=project, status=status, limit=limit)

    def show(self, journey_id: str) -> dict[str, Any] | None:
        """Get a journey with all its linked entities.

        Uses bulk-fetch to avoid N+1 queries when many relationships exist.
        """
        journey = self.c.journey_repo.get(journey_id)
        if not journey:
            return None

        full_id = journey["id"]
        rels = self.c.relationship_repo.get_all_for("journey", full_id)

        # Collect IDs by type, then fetch in bulk
        mem_ids: list[str] = []
        art_ids: list[str] = []
        mem_rel_map: dict[str, str] = {}  # mem_id -> relation
        art_rel_map: dict[str, str] = {}  # art_id -> relation

        for rel in rels:
            other_id = rel["target_id"] if rel["source_type"] == "journey" else rel["source_id"]
            other_type = rel["target_type"] if rel["source_type"] == "journey" else rel["source_type"]

            if other_type == "memory":
                mem_ids.append(other_id)
                mem_rel_map[other_id] = rel["relation"]
            elif other_type == "artifact":
                art_ids.append(other_id)
                art_rel_map[other_id] = rel["relation"]

        mem_by_id = {m["id"]: m for m in self.c.memory_repo.get_many(mem_ids)}
        art_by_id = {a["id"]: a for a in self.c.artifact_repo.get_many(art_ids)}

        linked_memories = [
            {"memory": mem_by_id[mid], "relation": mem_rel_map[mid]}
            for mid in mem_ids if mid in mem_by_id
        ]
        linked_artifacts = [
            {"artifact": art_by_id[aid], "relation": art_rel_map[aid]}
            for aid in art_ids if aid in art_by_id
        ]

        journey["linked_memories"] = linked_memories
        journey["linked_artifacts"] = linked_artifacts
        journey["relationships"] = rels
        return journey

    def link_memory(self, journey_id: str, memory_id: str) -> str:
        """Link a memory to a journey with 'part_of' relationship."""
        rel = Relationship(
            source_type="memory",
            source_id=memory_id,
            target_type="journey",
            target_id=journey_id,
            relation=RelationType.PART_OF,
        )
        self.c.relationship_repo.insert(rel.model_dump())
        return rel.id
