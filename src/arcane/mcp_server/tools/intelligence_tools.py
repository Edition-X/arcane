"""MCP tool handlers for intelligence/insights operations."""

from __future__ import annotations

import json
import os

from arcane.domain.scope import canonicalize_project
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.services.container import ServiceContainer


def handle_insights(
    container: ServiceContainer,
    project: str | None = None,
    limit: int = 10,
) -> str:
    project = canonicalize_project(project or os.path.basename(os.getcwd()), container.config.projects.aliases)
    insights = container.insight_repo.list_all(project=project, unacknowledged_only=True, limit=limit)
    return json.dumps(
        [
            {
                "id": i["id"],
                "type": i["insight_type"],
                "title": i["title"],
                "severity": i["severity"],
                "created_at": i["created_at"][:10],
            }
            for i in insights
        ]
    )


def handle_insights_ack(container: ServiceContainer, insight_id: str) -> str:
    try:
        acked = container.insight_repo.acknowledge(insight_id)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if not acked:
        return json.dumps({"error": f"Insight not found: {insight_id}"})
    return json.dumps({"acknowledged": True, "insight_id": insight_id})
