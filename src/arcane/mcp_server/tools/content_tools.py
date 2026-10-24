"""MCP tool handlers for content generation (structured briefs)."""

from __future__ import annotations

import json

from arcane.domain.scope import resolve_write_scope
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.infra.redaction import redact
from arcane.plugins.registry import create_plugin
from arcane.services.container import ServiceContainer
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService


def handle_draft_blog(
    container: ServiceContainer,
    journey_id: str | None = None,
    project: str | None = None,
) -> str:
    """Generate a structured blog brief from a journey or project memories."""
    if journey_id:
        js = JourneyService(container)
        try:
            journey = js.show(journey_id)
        except IdentifierResolutionError as exc:
            return json.dumps({"error": str(exc)})
        if not journey:
            return json.dumps({"error": f"Journey {journey_id} not found"})

        brief = create_plugin("content", "blog", container).generate({"journey": journey})
        return json.dumps({"brief": redact(brief, container.ignore_patterns), "journey_id": journey["id"]})

    if project:
        brief = _build_project_brief(container, project)
        return json.dumps({"brief": redact(brief, container.ignore_patterns), "project": project})

    return json.dumps({"error": "Provide journey_id or project to generate brief"})


def handle_draft_adr(
    container: ServiceContainer,
    memory_id: str,
) -> str:
    """Generate a structured ADR brief from a decision memory."""
    try:
        full_id = container.memory_repo.resolve_prefix(memory_id)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    mem = container.memory_repo.get(full_id) if full_id else None
    if not mem:
        return json.dumps({"error": f"Memory {memory_id} not found"})

    detail = container.memory_repo.get_details(mem["id"])
    detail_body = detail["body"] if detail else ""

    brief = create_plugin("content", "adr", container).generate({"memory": mem, "details": detail_body})
    return json.dumps({"brief": redact(brief, container.ignore_patterns), "memory_id": mem["id"]})


def _build_project_brief(container: ServiceContainer, project: str) -> str:
    """Build a blog brief from recent project memories when no journey is available."""
    svc = MemoryService(container)
    scope = resolve_write_scope(project, container.config)
    memories, _ = svc.get_context(limit=20, project=scope.project, org=scope.org)
    brief = create_plugin("content", "blog", container).generate({"memories": memories, "project": scope.project})
    return str(brief) if brief else f"# Blog Brief: {scope.project}\n\n*No memories found for this project.*"
