"""MCP tool handlers for relationship operations."""

from __future__ import annotations

import json

from arcane.domain.enums import RelationType
from arcane.domain.models import Relationship
from arcane.infra.db.ids import ENTITY_TABLES, IdentifierResolutionError, resolve_entity_id
from arcane.services.container import ServiceContainer


def handle_link(
    container: ServiceContainer,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation: str,
) -> str:
    valid_types = set(ENTITY_TABLES)
    if source_type not in valid_types or target_type not in valid_types:
        return json.dumps({"error": f"Invalid entity type. Must be one of: {sorted(valid_types)}"})

    valid_relations = {r.value for r in RelationType}
    if relation not in valid_relations:
        return json.dumps({"error": f"Invalid relation. Must be one of: {sorted(valid_relations)}"})

    resolved: dict[str, str] = {}
    for side, entity_type, entity_id in (("Source", source_type, source_id), ("Target", target_type, target_id)):
        try:
            full_id = resolve_entity_id(container.db, entity_type, entity_id)
        except IdentifierResolutionError as exc:
            return json.dumps({"error": f"{side} {entity_type} '{entity_id}': {exc}"})
        if full_id is None:
            return json.dumps({"error": f"{side} {entity_type} not found: {entity_id}"})
        resolved[side] = full_id
    source_full, target_full = resolved["Source"], resolved["Target"]

    # Store full IDs: relationship lookups match exactly, so a stored prefix
    # would make the edge invisible to journey_show and trace.
    rel = Relationship(
        source_type=source_type,
        source_id=source_full,
        target_type=target_type,
        target_id=target_full,
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
    try:
        full_id = resolve_entity_id(container.db, entity_type, entity_id)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if full_id is None:
        return json.dumps({"error": f"{entity_type.capitalize()} not found: {entity_id}"})
    rels = container.relationship_repo.trace(entity_type, full_id, max_depth=max_depth)
    return json.dumps(
        [
            {
                "id": r["id"],
                "source_type": r["source_type"],
                "source_id": r["source_id"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "relation": r["relation"],
            }
            for r in rels
        ]
    )
