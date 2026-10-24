"""JourneyService — orchestrates decision journey operations."""

from __future__ import annotations

from typing import Any

from arcane.domain.enums import RelationType
from arcane.domain.models import Journey, Relationship
from arcane.domain.scope import canonicalize_project, resolve_write_scope
from arcane.infra.redaction import redact, redact_values
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
        resolved = resolve_write_scope(project, self.c.config)
        journey = Journey(
            title=redact(title, self.c.ignore_patterns),
            project=resolved.project,
            org=resolved.org,
            linear_issue_id=redact(linear_issue_id, self.c.ignore_patterns) if linear_issue_id else None,
        )
        self.c.journey_repo.insert(journey.model_dump())
        return {"id": journey.id, "title": journey.title, "project": journey.project, "org": journey.org}

    def update(self, journey_id: str, summary: str | None = None, *, org: str | None = None, **fields: Any) -> bool:
        journey = self.c.journey_repo.get(journey_id, org=org)
        if not journey:
            return False
        journey_id = journey["id"]
        if summary:
            fields["summary"] = summary
        fields = redact_values(fields, self.c.ignore_patterns)
        assert isinstance(fields, dict)
        return self.c.journey_repo.update(
            journey_id,
            event_type="updated",
            event_summary=fields.get("summary"),
            **fields,
        )

    def complete(self, journey_id: str, summary: str | None = None, *, org: str | None = None) -> bool:
        journey = self.c.journey_repo.get(journey_id, org=org)
        if not journey:
            return False
        journey_id = journey["id"]
        return self.c.journey_repo.complete(
            journey_id, summary=redact(summary, self.c.ignore_patterns) if summary else None
        )

    def abandon(self, journey_id: str, reason: str | None = None, *, org: str | None = None) -> bool:
        """Mark a journey abandoned, recording the reason in its history and summary."""
        journey = self.c.journey_repo.get(journey_id, org=org)
        if not journey:
            return False
        journey_id = journey["id"]
        return self.c.journey_repo.abandon(
            journey_id,
            reason=redact(reason, self.c.ignore_patterns) if reason else None,
        )

    def delete(self, journey_id: str, *, org: str | None = None) -> bool:
        """Delete a journey and every relationship that references it."""
        with self.c.db.transaction():
            journey = self.c.journey_repo.get(journey_id, org=org)
            if not journey:
                return False
            full_id = journey["id"]
            for rel in self.c.relationship_repo.get_all_for("journey", full_id):
                self.c.relationship_repo.delete(rel["id"])
            return self.c.journey_repo.delete(full_id)

    def get(self, journey_id: str, *, org: str | None = None) -> dict[str, Any] | None:
        return self.c.journey_repo.get(journey_id, org=org)

    def list(
        self,
        project: str | None = None,
        status: str | None = None,
        limit: int = 20,
        org: str | None = None,
    ) -> list[dict[str, Any]]:
        if project:
            project = canonicalize_project(project, self.c.config.projects.aliases)
        return self.c.journey_repo.list_all(project=project, status=status, limit=limit, org=org)

    def show(self, journey_id: str, *, org: str | None = None) -> dict[str, Any] | None:
        """Get a journey with all its linked entities.

        Uses bulk-fetch to avoid N+1 queries when many relationships exist.
        """
        journey = self.c.journey_repo.get(journey_id, org=org)
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

        # Legacy edges may cross ownership boundaries. Never expose another
        # org's records through an otherwise correctly scoped journey.
        mem_by_id = {
            m["id"]: m
            for m in self.c.memory_repo.get_many(mem_ids)
            if m.get("org", "") == journey["org"] and m["project"] == journey["project"]
        }
        art_by_id = {
            a["id"]: a
            for a in self.c.artifact_repo.get_many(art_ids)
            if a.get("org", "") == journey["org"] and a["project"] == journey["project"]
        }

        linked_memories = [
            {"memory": mem_by_id[mid], "relation": mem_rel_map[mid]} for mid in mem_ids if mid in mem_by_id
        ]
        linked_artifacts = [
            {"artifact": art_by_id[aid], "relation": art_rel_map[aid]} for aid in art_ids if aid in art_by_id
        ]

        journey["linked_memories"] = linked_memories
        journey["linked_artifacts"] = linked_artifacts
        journey["events"] = self.c.journey_repo.list_events(full_id)
        visible_ids = {full_id, *mem_by_id, *art_by_id}
        journey["relationships"] = [r for r in rels if r["source_id"] in visible_ids and r["target_id"] in visible_ids]
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
        with self.c.db.transaction():
            self.c.relationship_repo.insert(rel.model_dump())
        return rel.id
