"""Record what each MCP lookup returned, for ``arcane analyze usage``.

The server calls :func:`record_tool_call` after a tool replies. Only lookups
(and ``memory_update``, which shows a recalled memory was worth acting on) are
recorded; saves and admin tools are not. Recording is best effort: any failure
is logged and swallowed so a lookup never fails because its log row did not.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from arcane.domain.scope import canonicalize_project, resolve_scope
from arcane.infra.redaction import redact
from arcane.services.container import ServiceContainer

logger = logging.getLogger(__name__)

RECORDED_TOOLS = frozenset(
    {
        "memory_search",
        "memory_context",
        "memory_details",
        "memory_update",
        "journey_show",
        "artifact_search",
        "artifact_details",
    }
)


def _hits(tool: str, data: Any) -> list[tuple[str, str]]:
    """The ``(entity_type, id)`` pairs a tool's JSON reply put in front of the agent, in order."""
    if tool == "memory_search" and isinstance(data, list):
        return [("memory", r["id"]) for r in data if isinstance(r, dict) and r.get("id")]
    if tool in ("memory_context", "resource_context") and isinstance(data, dict):
        return [("memory", m["id"]) for m in data.get("memories", []) if m.get("id")]
    if tool == "memory_details" and isinstance(data, dict) and data.get("memory_id"):
        return [("memory", data["memory_id"])]
    if tool == "journey_show" and isinstance(data, dict) and data.get("id"):
        return [("journey", data["id"])]
    if tool == "artifact_search" and isinstance(data, list):
        return [("artifact", r["id"]) for r in data if isinstance(r, dict) and r.get("id")]
    if tool == "artifact_details" and isinstance(data, dict) and data.get("id"):
        return [("artifact", data["id"])]
    return []


def record_tool_call(
    container: ServiceContainer,
    *,
    session_id: str,
    client: str | None,
    tool: str,
    arguments: dict[str, Any],
    result_text: str,
    is_error: bool,
    duration_ms: int,
) -> None:
    """Record one lookup. Never raises."""
    usage = container.config.usage
    if not usage.enabled or (tool not in RECORDED_TOOLS and tool != "resource_context"):
        return
    try:
        try:
            data = json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            data = None
        hits = [] if is_error else _hits(tool, data)

        if tool == "memory_update" and not is_error:
            # The reply only echoes the prefix the agent sent; store the full ID.
            full_id = container.memory_repo.resolve_prefix(str(arguments.get("memory_id", "")))
            hits = [("memory", full_id)] if full_id else []

        scope = data.get("scope") if isinstance(data, dict) else None
        if isinstance(scope, dict):
            org, project = scope.get("org"), scope.get("project")
        else:
            resolved = resolve_scope(os.getcwd(), container.config)
            org = arguments.get("org") or resolved.org
            explicit = arguments.get("project")
            project = (
                canonicalize_project(explicit, container.config.projects.aliases) if explicit else resolved.project
            )

        raw_query = str(arguments.get("query") or "")
        keyword_matches = container.retrieval_repo.keyword_matches(raw_query) if raw_query else None
        query = redact(raw_query, container.ignore_patterns) if raw_query and usage.log_queries else None

        container.retrieval_repo.record(
            {
                "session_id": session_id,
                "client": client,
                "tool": tool,
                "org": org,
                "project": project,
                "query": query,
                "keyword_matches": keyword_matches,
                "duration_ms": duration_ms,
                "is_error": is_error,
            },
            hits,
        )
    except Exception:
        logger.warning("Could not record usage for tool '%s'", tool, exc_info=True)
