"""IngestionService — orchestrates ingestion plugins and artifact storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from arcane.domain.enums import RelationType
from arcane.domain.models import Relationship
from arcane.domain.scope import resolve_write_scope
from arcane.infra.redaction import redact_values
from arcane.plugins.protocols import IngestionPlugin
from arcane.services.container import ServiceContainer


class IngestionService:
    """Runs ingestion plugins and stores their output as artifacts."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def run_plugin(
        self,
        plugin: IngestionPlugin,
        project: str | None = None,
        since: datetime | None = None,
        journey_id: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Run a single ingestion plugin and store results."""
        project = resolve_write_scope(project, self.c.config, repo_path=repo_path).project
        artifacts = plugin.ingest(project=project, since=since)

        ingested = 0
        skipped = 0

        for art in artifacts:
            art.update(redact_values(art, self.c.ignore_patterns))
            art["project"] = project
            with self.c.db.transaction():
                # Resolve and link inside one transaction so repeated ingestion
                # cannot create duplicate artifacts or journey relationships.
                existing = self.c.artifact_repo.find_by_external(
                    art["artifact_type"],
                    art["external_id"],
                    art["project"],
                )
                artifact_id = existing["id"] if existing else art["id"]
                if existing:
                    skipped += 1
                else:
                    self.c.artifact_repo.insert(art)
                # Auto-link to journey if specified
                if journey_id and not self.c.relationship_repo.exists(
                    "artifact", artifact_id, "journey", journey_id, RelationType.PART_OF.value
                ):
                    rel = Relationship(
                        source_type="artifact",
                        source_id=artifact_id,
                        target_type="journey",
                        target_id=journey_id,
                        relation=RelationType.PART_OF,
                    )
                    self.c.relationship_repo.insert(rel.model_dump())
            if not existing:
                ingested += 1

        return {
            "plugin": plugin.name,
            "ingested": ingested,
            "skipped": skipped,
            "total": len(artifacts),
        }

    def run_all(
        self,
        plugins: list[IngestionPlugin],
        project: str | None = None,
        since: datetime | None = None,
        journey_id: str | None = None,
        repo_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run multiple ingestion plugins."""
        return [
            self.run_plugin(plugin, project=project, since=since, journey_id=journey_id, repo_path=repo_path)
            for plugin in plugins
        ]
