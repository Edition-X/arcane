"""IngestionService — orchestrates ingestion plugins and artifact storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from arcane.domain.enums import RelationType
from arcane.domain.models import Relationship
from arcane.plugins.protocols import IngestionPlugin
from arcane.services.container import ServiceContainer


class IngestionService:
    """Runs ingestion plugins and stores their output as artifacts."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def run_plugin(
        self,
        plugin: IngestionPlugin,
        project: str,
        since: datetime | None = None,
        journey_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a single ingestion plugin and store results."""
        artifacts = plugin.ingest(project=project, since=since)

        ingested = 0
        skipped = 0

        for art in artifacts:
            # Dedup: check if artifact already exists by type + external_id + project
            existing = self.c.artifact_repo.find_by_external(
                art["artifact_type"], art["external_id"], art["project"],
            )
            if existing:
                skipped += 1
                continue

            self.c.artifact_repo.insert(art)
            ingested += 1

            # Auto-link to journey if specified
            if journey_id:
                rel = Relationship(
                    source_type="artifact",
                    source_id=art["id"],
                    target_type="journey",
                    target_id=journey_id,
                    relation=RelationType.PART_OF,
                )
                self.c.relationship_repo.insert(rel.model_dump())

        return {
            "plugin": plugin.name,
            "ingested": ingested,
            "skipped": skipped,
            "total": len(artifacts),
        }

    def run_all(
        self,
        plugins: list[IngestionPlugin],
        project: str,
        since: datetime | None = None,
        journey_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run multiple ingestion plugins."""
        return [
            self.run_plugin(plugin, project=project, since=since, journey_id=journey_id)
            for plugin in plugins
        ]
