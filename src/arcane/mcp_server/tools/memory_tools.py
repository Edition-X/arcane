"""MCP tool handlers for memory operations."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput
from arcane.domain.scope import GLOBAL_ORG, resolve_scope
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.services.memory import MemoryService

logger = logging.getLogger(__name__)

VALID_CATEGORIES = tuple(c.value for c in Category)
VALID_SCOPES = ("project", "org", "global")

SAVE_DESCRIPTION = """Save a memory for future sessions. You MUST call this before ending any session where you made changes, fixed bugs, made decisions, or learned something.

Save when you:
- Made an architectural or design decision
- Fixed a bug (include root cause and solution)
- Discovered a non-obvious pattern or gotcha
- Learned something about the codebase
- Set up infrastructure, tooling, or configuration

When filling `details`, prefer: Context, Options considered, Decision, Tradeoffs, Follow-up."""

SEARCH_DESCRIPTION = """Search memories using keyword and semantic search. Call this at session start and when the user's request relates to a topic with prior context.

Results omit why/impact by default; call memory_details for the full body."""

CONTEXT_DESCRIPTION = """Get memory context for the current project. Call this at session start to load prior decisions, bugs, and context.

Use the `detail` parameter to control token usage:
- minimal: title + category only (~500 tokens for 10 memories)
- standard: title, category, tags, date, what (default)
- full: all fields including why and impact"""


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
    org: str | None = None,
    scope: str | None = "project",
    journey_id: str | None = None,
    ttl_days: int | None = None,
    confidence: float | None = None,
    source: str | None = None,
) -> str:
    handler_warnings: list[str] = []

    # Sanitise category at the handler boundary so the domain model stays strict
    if category and category not in VALID_CATEGORIES:
        logger.debug("Unknown category '%s' received via MCP; coercing to 'context'", category)
        handler_warnings.append(
            f"Unknown category '{category}' coerced to 'context'. Valid values: {', '.join(sorted(VALID_CATEGORIES))}."
        )
        category = "context"

    # Resolve the (org, project) scope for this save.
    scope = (scope or "project").lower()
    if scope not in VALID_SCOPES:
        handler_warnings.append(
            f"Unknown scope '{scope}' coerced to 'project'. Valid values: {', '.join(VALID_SCOPES)}."
        )
        scope = "project"

    resolved = resolve_scope(os.getcwd(), svc.c.config)
    if scope == "global":
        org_final, project_final = GLOBAL_ORG, ""
    elif scope == "org":
        org_final, project_final = (org or resolved.org), ""
    else:
        org_final = org or resolved.org
        project_final = project if project is not None else resolved.project
        if not project_final.strip():
            handler_warnings.append(
                "empty_project: no project resolved for this save — it will be invisible to "
                "project-scoped recall. Pass `project` explicitly, or use scope='org'/'global' "
                "if this is intentionally broader knowledge."
            )

    raw = RawMemoryInput(
        title=title[:60],
        what=what,
        why=why,
        impact=impact,
        tags=tags or [],
        category=category,
        related_files=related_files or [],
        details=details,
        source=source,
        journey_id=journey_id,
        ttl_days=ttl_days,
        confidence=confidence,
    )
    result = svc.save(raw, project=project_final, org=org_final)
    result["scope"] = {"org": org_final, "project": project_final}
    if handler_warnings:
        result["warnings"] = handler_warnings + result.get("warnings", [])
    return json.dumps(result)


def _normalize_limit(limit: int | None, default: int) -> int:
    if limit is None or limit <= 0:
        return default
    return limit


def _normalize_detail(detail: str | None) -> str:
    """Coerce a `detail` argument to a known level, defaulting to "standard".

    Shared by handle_search and handle_context so both tools fall back the
    same way for an unrecognised value.
    """
    detail = detail or "standard"
    if detail not in ("minimal", "standard", "full"):
        detail = "standard"
    return detail


def _search_hit(r: dict, detail: str) -> dict:
    # Search hits and context memories don't share a field-selection helper:
    # search carries score/project/org/ttl/confidence sourced straight off
    # the row, while context carries a human-formatted date and no score —
    # unifying them would need per-field branching that reads worse than
    # two short builders.
    score = round(r.get("score", 0), 2)
    if detail == "minimal":
        return {
            "id": r["id"],
            "title": r["title"],
            "category": r.get("category"),
            "score": score,
        }
    if detail == "full":
        return {
            "id": r["id"],
            "title": r["title"],
            "what": r["what"],
            "why": r.get("why"),
            "impact": r.get("impact"),
            "category": r.get("category"),
            "tags": r.get("tags", []),  # already list[str] from repo
            "project": r.get("project"),
            "org": r.get("org", ""),
            "created_at": r.get("created_at", "")[:10],
            "score": score,
            "has_details": bool(r.get("has_details")),
            "ttl_days": r.get("ttl_days"),
            "confidence": r.get("confidence"),
        }
    # standard (default)
    return {
        "id": r["id"],
        "title": r["title"],
        "category": r.get("category"),
        "score": score,
        "what": r["what"],
        "tags": r.get("tags", []),
        "project": r.get("project"),
        "date": r.get("created_at", "")[:10],
        "has_details": bool(r.get("has_details")),
    }


def handle_search(
    svc: MemoryService,
    query: str,
    limit: int | None = 5,
    project: str | None = None,
    org: str | None = None,
    include_org: bool = True,
    include_global: bool = True,
    detail: str | None = "standard",
) -> str:
    resolved = resolve_scope(os.getcwd(), svc.c.config)
    org_final = org or resolved.org
    project_final = project if project is not None else resolved.project
    detail = _normalize_detail(detail)

    results = svc.search(
        query,
        limit=_normalize_limit(limit, 5),
        project=project_final,
        org=org_final,
        include_org=include_org,
        include_global=include_global,
    )

    clean = [_search_hit(r, detail) for r in results]
    return json.dumps(clean)


def handle_context(
    svc: MemoryService,
    project: str | None = None,
    limit: int | None = 10,
    detail: str | None = "standard",
    query: str | None = None,
    org: str | None = None,
    scope: str | None = None,
    include_org: bool = True,
    include_global: bool = True,
) -> str:
    # Resolve the current (org, project) scope; explicit args win.
    resolved = resolve_scope(os.getcwd(), svc.c.config)
    org_final = org or resolved.org
    project_final = project if project is not None else resolved.project

    # Optional `scope` narrows retrieval to a single layer.
    inc_org, inc_global = include_org, include_global
    if scope == "project":
        inc_org, inc_global = False, False
    elif scope == "org":
        project_final, inc_org, inc_global = "", True, False
    elif scope == "global":
        org_final, project_final, inc_org, inc_global = GLOBAL_ORG, "", True, False

    # Honour the configured semantic mode rather than hardcoding "never"
    results, total = svc.get_context(
        limit=_normalize_limit(limit, 10),
        project=project_final,
        org=org_final,
        query=query or None,
        include_org=inc_org,
        include_global=inc_global,
    )

    # Normalise detail level — fall back to standard for unknown values
    detail = _normalize_detail(detail)

    memories = []
    for r in results:
        date_str = r.get("created_at", "")[:10]
        try:
            dt = datetime.fromisoformat(date_str)
            date_display = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_display = date_str

        if detail == "minimal":
            memories.append(
                {
                    "id": r["id"],
                    "title": r.get("title", "Untitled"),
                    "category": r.get("category", ""),
                }
            )
        elif detail == "full":
            memories.append(
                {
                    "id": r["id"],
                    "title": r.get("title", "Untitled"),
                    "category": r.get("category", ""),
                    "tags": r.get("tags", []),
                    "date": date_display,
                    "what": r.get("what", ""),
                    "why": r.get("why"),
                    "impact": r.get("impact"),
                }
            )
        else:
            # standard (default)
            memories.append(
                {
                    "id": r["id"],
                    "title": r.get("title", "Untitled"),
                    "category": r.get("category", ""),
                    "tags": r.get("tags", []),  # already list[str] from repo
                    "date": date_display,
                    "what": r.get("what", ""),
                }
            )

    payload: dict = {
        "total": total,
        "showing": len(memories),
        "memories": memories,
        "scope": {"org": org_final, "project": project_final},
        "message": "Use memory_search for specific topics. Save memories before session ends.",
    }

    # Surface pending intelligence at session start (not in minimal mode —
    # that's the token-pinching path).
    if detail != "minimal" and project_final:
        pending = svc.c.insight_repo.list_all(project=project_final, unacknowledged_only=True, limit=3)
        if pending:
            payload["insights"] = [
                {
                    "id": i["id"],
                    "type": i["insight_type"],
                    "title": i["title"],
                    "severity": i["severity"],
                    "created_at": i["created_at"][:10],
                }
                for i in pending
            ]

    # Surface active journeys idle for more than 14 days so the agent is
    # prompted to complete or abandon them instead of letting them rot.
    if detail != "minimal" and project_final:
        stale = svc.c.journey_repo.list_stale_active(14, project=project_final)[:5]
        if stale:
            payload["stale_journeys"] = [
                {"id": j["id"], "title": j["title"], "last_update": (j.get("updated_at") or "")[:10]} for j in stale
            ]
            payload["message"] = (payload.get("message") or "") + (
                f" {len(stale)} active journey(s) idle >14 days: call journey_complete or journey_abandon."
            )

    return json.dumps(payload)


def handle_details(svc: MemoryService, memory_id: str) -> str:
    try:
        detail = svc.get_details(memory_id)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if not detail:
        return json.dumps({"error": f"No details found for {memory_id}"})
    return json.dumps({"memory_id": detail["memory_id"], "body": detail["body"]})


def handle_update(
    svc: MemoryService,
    memory_id: str,
    what: str | None = None,
    why: str | None = None,
    impact: str | None = None,
    tags: list[str] | None = None,
    details_append: str | None = None,
) -> str:
    try:
        updated = svc.update(
            memory_id,
            what=what,
            why=why,
            impact=impact,
            tags=tags,
            details_append=details_append,
        )
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if not updated:
        return json.dumps({"error": f"Memory not found: {memory_id}"})
    return json.dumps({"updated": True, "memory_id": memory_id})


def handle_delete(svc: MemoryService, memory_id: str) -> str:
    try:
        deleted = svc.delete(memory_id)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if not deleted:
        return json.dumps({"error": f"Memory not found: {memory_id}"})
    return json.dumps({"deleted": True, "memory_id": memory_id})
