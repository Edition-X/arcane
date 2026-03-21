"""MCP tool handlers for relationship operations."""

from __future__ import annotations

import json

from arcane.domain.enums import RelationType
from arcane.domain.models import Relationship
from arcane.services.container import ServiceContainer


def handle_link(
    container: ServiceContainer,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation: str,
) -> str:
    valid_types = {"memory", "journey", "artifact"}
    if source_type not in valid_types or target_type not in valid_types:
        return json.dumps({"error": f"Invalid entity type. Must be one of: {valid_types}"})

    valid_relations = {r.value for r in RelationType}
    if relation not in valid_relations:
        return json.dumps({"error": f"Invalid relation. Must be one of: {valid_relations}"})

    rel = Relationship(
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=RelationType(relation),
    )
    container.relationship_repo.insert(rel.model_dump())
    return json.dumps({"id": rel.id, "created": True})


def handle_trace(
    container: ServiceContainer,
    entity_type: str,
    entity_id: str,
    max_depth: int = 5,
) -> str:
    rels = container.relationship_repo.trace(entity_type, entity_id, max_depth=max_depth)
    return json.dumps([
        {
            "id": r["id"],
            "source_type": r["source_type"],
            "source_id": r["source_id"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "relation": r["relation"],
        }
        for r in rels
    ])
