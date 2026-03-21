"""MCP tool handlers for journey operations."""

from __future__ import annotations

import json
import os
from typing import Any

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
    return json.dumps({"updated": updated, "journey_id": journey_id})


def handle_journey_complete(
    svc: JourneyService,
    journey_id: str,
    summary: str | None = None,
) -> str:
    completed = svc.complete(journey_id, summary=summary)
    return json.dumps({"completed": completed, "journey_id": journey_id})


def handle_journey_list(
    svc: JourneyService,
    project: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    project = project or os.path.basename(os.getcwd())
    journeys = svc.list(project=project, status=status, limit=limit)
    return json.dumps([
        {
            "id": j["id"],
            "title": j["title"],
            "status": j["status"],
            "project": j["project"],
            "started_at": j["started_at"][:10],
            "completed_at": (j.get("completed_at") or "")[:10] or None,
        }
        for j in journeys
    ])
