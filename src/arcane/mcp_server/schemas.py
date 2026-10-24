"""Generate shared request constraints from the domain input model."""

from __future__ import annotations

from typing import Any

from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput


def memory_save_schema() -> dict[str, Any]:
    """Domain save fields plus the MCP interface's scope selectors.

    Optional values are omitted on the wire, matching the existing MCP API;
    the domain model additionally accepts None for internal Python callers.
    """
    schema = RawMemoryInput.model_json_schema()
    properties = schema["properties"]
    for field in properties.values():
        if "anyOf" in field:
            choices = [choice for choice in field.pop("anyOf") if choice.get("type") != "null"]
            field.update(choices[0])
        if field.get("default", ...) is None:
            field.pop("default")
    properties["category"]["enum"] = [category.value for category in Category]
    descriptions = {
        "title": "Short title, max 60 chars.",
        "what": "1-2 sentences. The essence.",
        "why": "Reasoning behind it.",
        "impact": "What changed.",
        "details": "Full context.",
        "source": "Source agent; defaults to the connecting MCP client.",
        "journey_id": "Link to a journey.",
        "supersedes": "ID or prefix of an earlier memory this one replaces.",
        "ttl_days": "Days until this memory expires. Omit for permanent memories.",
        "confidence": "Confidence in accuracy 0.0–1.0. Default: omit.",
    }
    for name, description in descriptions.items():
        properties[name]["description"] = description
    properties.update(
        project={"type": "string"},
        org={
            "type": "string",
            "pattern": "^[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*$",
            "description": "Company/org slug. Omit to auto-detect from the git remote owner.",
        },
        scope={
            "type": "string",
            "enum": ["project", "org", "global"],
            "default": "project",
            "description": "Knowledge layer: this project, its org, or global knowledge shared everywhere.",
        },
    )
    return schema
