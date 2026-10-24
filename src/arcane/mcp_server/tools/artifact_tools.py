"""MCP tool handlers for artifact retrieval."""

from __future__ import annotations

import json
from typing import Any

from arcane.domain.scope import resolve_write_scope
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.services.container import ServiceContainer


def handle_artifact_search(
    container: ServiceContainer,
    query: str,
    project: str | None = None,
    artifact_type: str | None = None,
    limit: int = 10,
) -> str:
    """Search ingested artifact metadata and raw content."""
    scope = resolve_write_scope(project, container.config)
    artifacts = container.artifact_repo.fts_search(
        query, project=scope.project, org=scope.org, artifact_type=artifact_type, limit=limit
    )
    return json.dumps([_artifact_summary(artifact) for artifact in artifacts])


def handle_artifact_details(container: ServiceContainer, artifact_id: str) -> str:
    """Return full artifact data, including parsed raw ingestion data."""
    try:
        artifact = container.artifact_repo.get(artifact_id, org=resolve_write_scope(None, container.config).org)
    except IdentifierResolutionError as exc:
        return json.dumps({"error": str(exc)})
    if not artifact:
        return json.dumps({"error": f"Artifact not found: {artifact_id}"})
    return json.dumps(artifact)


def _artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": artifact["id"],
        "title": artifact["title"],
        "artifact_type": artifact["artifact_type"],
        "external_id": artifact["external_id"],
        "url": artifact.get("url"),
        "project": artifact["project"],
        "created_at": artifact["created_at"],
        "score": artifact.get("score", 0),
    }
