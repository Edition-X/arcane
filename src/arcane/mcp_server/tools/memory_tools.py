"""MCP tool handlers for memory operations."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput
from arcane.services.memory import MemoryService

logger = logging.getLogger(__name__)

VALID_CATEGORIES = tuple(c.value for c in Category)

SAVE_DESCRIPTION = """Save a memory for future sessions. You MUST call this before ending any session where you made changes, fixed bugs, made decisions, or learned something.

Save when you:
- Made an architectural or design decision
- Fixed a bug (include root cause and solution)
- Discovered a non-obvious pattern or gotcha
- Learned something about the codebase
- Set up infrastructure, tooling, or configuration

When filling `details`, prefer: Context, Options considered, Decision, Tradeoffs, Follow-up."""

SEARCH_DESCRIPTION = """Search memories using keyword and semantic search. Call this at session start and when the user's request relates to a topic with prior context."""

CONTEXT_DESCRIPTION = """Get memory context for the current project. Call this at session start to load prior decisions, bugs, and context."""


def handle_save(
    svc: MemoryService,
    title: str,
    what: str,
    why: str | None = None,
    impact: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    related_files: list[str] | None = None,
    details: str | None = None,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    project = project or os.path.basename(os.getcwd())
    # Sanitise category at the handler boundary so the domain model stays strict
    if category and category not in VALID_CATEGORIES:
        logger.debug("Unknown category '%s' received via MCP; coercing to 'context'", category)
        category = "context"

    raw = RawMemoryInput(
        title=title[:60],
        what=what,
        why=why,
        impact=impact,
        tags=tags or [],
        category=category,
        related_files=related_files or [],
        details=details,
        source=None,
        journey_id=journey_id,
    )
    result = svc.save(raw, project=project)
    return json.dumps(result)


def handle_search(
    svc: MemoryService,
    query: str,
    limit: int = 5,
    project: str | None = None,
) -> str:
    results = svc.search(query, limit=limit, project=project)

    clean = []
    for r in results:
        clean.append({
            "id": r["id"],
            "title": r["title"],
            "what": r["what"],
            "why": r.get("why"),
            "impact": r.get("impact"),
            "category": r.get("category"),
            "tags": r.get("tags", []),  # already list[str] from repo
            "project": r.get("project"),
            "created_at": r.get("created_at", "")[:10],
            "score": round(r.get("score", 0), 2),
            "has_details": bool(r.get("has_details")),
        })
    return json.dumps(clean)


def handle_context(
    svc: MemoryService,
    project: str | None = None,
    limit: int = 10,
) -> str:
    project = project or os.path.basename(os.getcwd())
    # Honour the configured semantic mode rather than hardcoding "never"
    results, total = svc.get_context(limit=limit, project=project)

    memories = []
    for r in results:
        date_str = r.get("created_at", "")[:10]
        try:
            dt = datetime.fromisoformat(date_str)
            date_display = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_display = date_str

        memories.append({
            "id": r["id"],
            "title": r.get("title", "Untitled"),
            "category": r.get("category", ""),
            "tags": r.get("tags", []),  # already list[str] from repo
            "date": date_display,
        })

    return json.dumps({
        "total": total,
        "showing": len(memories),
        "memories": memories,
        "message": "Use memory_search for specific topics. Save memories before session ends.",
    })


def handle_details(svc: MemoryService, memory_id: str) -> str:
    detail = svc.get_details(memory_id)
    if not detail:
        return json.dumps({"error": f"No details found for {memory_id}"})
    return json.dumps({"memory_id": detail["memory_id"], "body": detail["body"]})


def handle_delete(svc: MemoryService, memory_id: str) -> str:
    deleted = svc.delete(memory_id)
    if not deleted:
        return json.dumps({"error": f"Memory not found: {memory_id}"})
    return json.dumps({"deleted": True, "memory_id": memory_id})
