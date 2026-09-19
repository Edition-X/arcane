"""MCP tool handlers for data ingestion."""

from __future__ import annotations

import json
import os

from arcane.infra.db.ids import IdentifierResolutionError
from arcane.plugins.protocols import IngestionPlugin, IntelligencePlugin
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
    except IdentifierResolutionError as exc:
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
    from arcane.plugins.builtin.git_ingest import GitIngestionPlugin

    plugin = GitIngestionPlugin(repo_path=repo_path or os.getcwd(), max_count=max_count)
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id, repo_path=repo_path)


def handle_ingest_gha(
    container: ServiceContainer,
    owner: str,
    repo: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest CI runs from GitHub Actions."""
    from arcane.plugins.builtin.gha_ingest import GHAIngestionPlugin

    plugin = GHAIngestionPlugin(owner=owner, repo=repo)
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id)


def handle_ingest_linear(
    container: ServiceContainer,
    team_id: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest tickets from Linear."""
    from arcane.plugins.builtin.linear_ingest import LinearIngestionPlugin

    plugin = LinearIngestionPlugin(team_id=team_id)
    return _run_ingestion(container, plugin, project=project, journey_id=journey_id)


def handle_analyze(
    container: ServiceContainer,
    plugin_name: str,
    project: str | None = None,
) -> str:
    """Run an intelligence analysis plugin."""
    from arcane.services.intelligence import IntelligenceService

    svc = IntelligenceService(container)

    plugin: IntelligencePlugin
    if plugin_name == "velocity":
        from arcane.plugins.builtin.velocity import VelocityTracker

        plugin = VelocityTracker(
            artifact_repo=container.artifact_repo,
            memory_repo=container.memory_repo,
            journey_repo=container.journey_repo,
        )
    elif plugin_name == "health":
        from arcane.plugins.builtin.health_audit import HealthAuditor

        plugin = HealthAuditor(
            memory_repo=container.memory_repo,
            journey_repo=container.journey_repo,
            aliases=container.config.projects.aliases,
        )
    else:
        return json.dumps({"error": f"Unknown analysis plugin: {plugin_name}"})

    result = svc.run_plugin(plugin, project=project)
    return json.dumps(result)
