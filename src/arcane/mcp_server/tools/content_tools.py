"""MCP tool handlers for content generation (structured briefs)."""

from __future__ import annotations

import json

from arcane.services.container import ServiceContainer
from arcane.services.journey import JourneyService


def handle_draft_blog(
    container: ServiceContainer,
    journey_id: str | None = None,
    project: str | None = None,
) -> str:
    """Generate a structured blog brief from a journey or project memories."""
    if journey_id:
        js = JourneyService(container)
        journey = js.show(journey_id)
        if not journey:
            return json.dumps({"error": f"Journey {journey_id} not found"})

        brief = _build_journey_brief(journey)
        return json.dumps({"brief": brief, "journey_id": journey["id"]})

    return json.dumps({"error": "Provide journey_id or project to generate brief"})


def handle_draft_adr(
    container: ServiceContainer,
    memory_id: str,
) -> str:
    """Generate a structured ADR brief from a decision memory."""
    mem = container.memory_repo.get(memory_id)
    if not mem:
        return json.dumps({"error": f"Memory {memory_id} not found"})

    detail = container.memory_repo.get_details(memory_id)
    detail_body = detail["body"] if detail else ""

    brief = f"""# ADR: {mem['title']}

## Status
Accepted

## Context
{mem.get('what', '')}

## Decision
{mem.get('why', 'See details below.')}

## Consequences
{mem.get('impact', 'See details below.')}

## Details
{detail_body}
"""
    return json.dumps({"brief": brief, "memory_id": mem["id"]})


def _build_journey_brief(journey: dict) -> str:
    lines = [
        f"# Blog Brief: {journey['title']}",
        "",
        f"**Project:** {journey['project']}",
        f"**Status:** {journey['status']}",
        f"**Started:** {journey['started_at'][:10]}",
    ]

    if journey.get("completed_at"):
        lines.append(f"**Completed:** {journey['completed_at'][:10]}")

    if journey.get("summary"):
        lines.append(f"\n## Summary\n{journey['summary']}")

    memories = journey.get("linked_memories", [])
    if memories:
        lines.append("\n## Decision Timeline\n")
        for item in memories:
            mem = item["memory"]
            rel = item["relation"]
            lines.append(f"### [{mem.get('category', 'note')}] {mem['title']}")
            lines.append(f"**What:** {mem['what']}")
            if mem.get("why"):
                lines.append(f"**Why:** {mem['why']}")
            if mem.get("impact"):
                lines.append(f"**Impact:** {mem['impact']}")
            lines.append(f"*Relation: {rel}*")
            lines.append("")

    artifacts = journey.get("linked_artifacts", [])
    if artifacts:
        lines.append("\n## Related Artifacts\n")
        for item in artifacts:
            art = item["artifact"]
            lines.append(f"- [{art['artifact_type']}] {art['title']}")
            if art.get("url"):
                lines.append(f"  URL: {art['url']}")

    return "\n".join(lines)
