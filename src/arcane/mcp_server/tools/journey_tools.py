"""MCP tool handlers for journey operations."""

from __future__ import annotations

import json
import os

from arcane.services.container import ServiceContainer
from arcane.services.journey import JourneyService


def handle_journey_start(
    svc: JourneyService,
    title: str,
    project: str | None = None,
    linear_issue_id: str | None = None,
) -> str:
    project = project or os.path.basename(os.getcwd())
    result = svc.start(title=title, project=project, linear_issue_id=linear_issue_id)
    return json.dumps(result)


def handle_journey_update(
    svc: JourneyService,
    journey_id: str,
    summary: str | None = None,
) -> str:
    updated = svc.update(journey_id, summary=summary)
    if not updated:
        return json.dumps({"error": f"Journey not found: {journey_id}"})
    return json.dumps({"updated": True, "journey_id": journey_id})


def handle_journey_complete(
    svc: JourneyService,
    journey_id: str,
    summary: str | None = None,
) -> str:
    completed = svc.complete(journey_id, summary=summary)
    if not completed:
        return json.dumps({"error": f"Journey not found: {journey_id}"})
    return json.dumps({"completed": True, "journey_id": journey_id})


def handle_journey_show(
    container: ServiceContainer,
    journey_id: str,
) -> str:
    svc = JourneyService(container)
    journey = svc.show(journey_id)
    if not journey:
        return json.dumps({"error": f"Journey not found: {journey_id}"})
    # Serialise linked entities to plain dicts (already dicts from repo)
    return json.dumps(
        {
            "id": journey["id"],
            "title": journey["title"],
            "status": journey["status"],
            "project": journey["project"],
            "summary": journey.get("summary"),
            "started_at": journey["started_at"][:10],
            "completed_at": (journey.get("completed_at") or "")[:10] or None,
            "linked_memories": [
                {
                    "memory_id": item["memory"]["id"],
                    "title": item["memory"]["title"],
                    "category": item["memory"].get("category"),
                    "relation": item["relation"],
                }
                for item in journey.get("linked_memories", [])
            ],
            "linked_artifacts": [
                {
                    "artifact_id": item["artifact"]["id"],
                    "title": item["artifact"]["title"],
                    "artifact_type": item["artifact"]["artifact_type"],
                    "relation": item["relation"],
                }
                for item in journey.get("linked_artifacts", [])
            ],
        }
    )


def handle_journey_list(
    svc: JourneyService,
    project: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    project = project or os.path.basename(os.getcwd())
    journeys = svc.list(project=project, status=status, limit=limit)
    return json.dumps(
        [
            {
                "id": j["id"],
                "title": j["title"],
                "status": j["status"],
                "project": j["project"],
                "started_at": j["started_at"][:10],
                "completed_at": (j.get("completed_at") or "")[:10] or None,
            }
            for j in journeys
        ]
    )
