"""Engineering velocity intelligence plugin.

Computes activity metrics across commits, memories, and journeys for a project.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from arcane.infra.db.artifact_repo import ArtifactRepository
from arcane.infra.db.journey_repo import JourneyRepository
from arcane.infra.db.memory_repo import MemoryRepository


class VelocityTracker:
    name = "velocity"

    def __init__(
        self,
        artifact_repo: ArtifactRepository | None = None,
        memory_repo: MemoryRepository | None = None,
        journey_repo: JourneyRepository | None = None,
    ) -> None:
        self.artifact_repo = artifact_repo
        self.memory_repo = memory_repo
        self.journey_repo = journey_repo

    def analyze(self, project: str) -> list[dict[str, Any]]:
        commit_count = 0
        memory_count = 0
        journey_count = 0
        completed_journeys = 0

        if self.artifact_repo:
            commits = self.artifact_repo.list_all(project=project, artifact_type="commit", limit=1000)
            commit_count = len(commits)

        if self.memory_repo:
            memory_count = self.memory_repo.count(project=project)

        journeys: list[dict] = []
        if self.journey_repo:
            journeys = self.journey_repo.list_all(project=project, limit=1000)
            journey_count = len(journeys)
            completed_journeys = sum(1 for j in journeys if j.get("status") == "completed")

        # Build insight
        now = datetime.now(timezone.utc).isoformat()
        body_lines = [
            f"Engineering velocity summary for '{project}':",
            "",
            f"  Commits:            {commit_count}",
            f"  Memories captured:  {memory_count}",
            f"  Journeys:           {journey_count} ({completed_journeys} completed)",
        ]

        if commit_count > 0 and memory_count > 0:
            ratio = memory_count / commit_count
            body_lines.append(f"  Memory/commit ratio: {ratio:.2f}")

        severity = "info"
        if memory_count == 0 and commit_count > 10:
            severity = "warning"
            body_lines.append(
                "\n  Warning: Many commits but no memories captured. Consider documenting decisions and learnings."
            )

        return [
            {
                "id": str(uuid.uuid4()),
                "insight_type": "velocity",
                "title": f"Velocity: {commit_count} commits, {memory_count} memories, {journey_count} journeys",
                "body": "\n".join(body_lines),
                "severity": severity,
                "project": project,
                "metadata": {
                    "commit_count": commit_count,
                    "memory_count": memory_count,
                    "journey_count": journey_count,
                    "completed_journeys": completed_journeys,
                },
                "created_at": now,
            }
        ]
