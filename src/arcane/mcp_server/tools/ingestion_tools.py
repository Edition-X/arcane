"""MCP tool handlers for data ingestion."""

from __future__ import annotations

import json
import os

from arcane.infra.db.ids import IdentifierResolutionError
from arcane.plugins.protocols import IngestionError, IngestionPlugin
from arcane.plugins.registry import PluginError, create_plugin
from arcane.services.container import ServiceContainer
from arcane.services.ingestion import IngestionService


def _run_ingestion(
    container: ServiceContainer,
    plugin: IngestionPlugin,
    project: str | None,
    journey_id: str | None,
    repo_path: str | None = None,
) -> str:
    try:
        result = IngestionService(container).run_plugin(
            plugin, project=project, journey_id=journey_id, repo_path=repo_path
        )
    except (IdentifierResolutionError, IngestionError) as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps(result)


def handle_ingest_git(
    container: ServiceContainer,
    project: str | None = None,
    repo_path: str | None = None,
    max_count: int = 100,
    journey_id: str | None = None,
) -> str:
    """Ingest commits from a git repository."""
    plugin = create_plugin(
        "ingestion", "git", container, {"repo_path": repo_path or os.getcwd(), "max_count": max_count}
    )
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id, repo_path=repo_path)


def handle_ingest_gha(
    container: ServiceContainer,
    owner: str,
    repo: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest CI runs from GitHub Actions."""
    plugin = create_plugin("ingestion", "github_actions", container, {"owner": owner, "repo": repo})
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id)


def handle_ingest_linear(
    container: ServiceContainer,
    team_id: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest tickets from Linear."""
    plugin = create_plugin("ingestion", "linear", container, {"team_id": team_id})
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id)


def handle_analyze(
    container: ServiceContainer,
    plugin_name: str,
    project: str | None = None,
) -> str:
    """Run an intelligence analysis plugin."""
    from arcane.services.intelligence import IntelligenceService

    try:
        plugin = create_plugin("intelligence", plugin_name, container)
    except PluginError as exc:
        return json.dumps({"error": str(exc)})
    result = IntelligenceService(container).run_plugin(plugin, project=project)
    return json.dumps(result)
