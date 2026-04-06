"""MCP tool handlers for intelligence/insights operations."""

from __future__ import annotations

import json
import os

from arcane.services.container import ServiceContainer


def handle_insights(
    container: ServiceContainer,
    project: str | None = None,
    limit: int = 10,
) -> str:
    project = project or os.path.basename(os.getcwd())
    insights = container.insight_repo.list_all(
        project=project, unacknowledged_only=True, limit=limit
    )
    return json.dumps([
        {
            "id": i["id"],
            "type": i["insight_type"],
            "title": i["title"],
            "severity": i["severity"],
            "created_at": i["created_at"][:10],
        }
        for i in insights
    ])


def handle_insights_ack(container: ServiceContainer, insight_id: str) -> str:
    acked = container.insight_repo.acknowledge(insight_id)
    if not acked:
        return json.dumps({"error": f"Insight not found: {insight_id}"})
    return json.dumps({"acknowledged": True, "insight_id": insight_id})
