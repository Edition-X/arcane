"""MCP tool handlers for data ingestion."""

from __future__ import annotations

import json
import os

from arcane.plugins.protocols import IntelligencePlugin
from arcane.services.container import ServiceContainer
from arcane.services.ingestion import IngestionService


def handle_ingest_git(
    container: ServiceContainer,
    project: str | None = None,
    repo_path: str | None = None,
    max_count: int = 100,
    journey_id: str | None = None,
) -> str:
    """Ingest commits from a git repository."""
    from arcane.plugins.builtin.git_ingest import GitIngestionPlugin

    project = project or os.path.basename(os.getcwd())
    plugin = GitIngestionPlugin(repo_path=repo_path or os.getcwd(), max_count=max_count)
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    return json.dumps(result)


def handle_ingest_gha(
    container: ServiceContainer,
    owner: str,
    repo: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest CI runs from GitHub Actions."""
    from arcane.plugins.builtin.gha_ingest import GHAIngestionPlugin

    project = project or os.path.basename(os.getcwd())
    plugin = GHAIngestionPlugin(owner=owner, repo=repo)
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    return json.dumps(result)


def handle_ingest_linear(
    container: ServiceContainer,
    team_id: str,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """Ingest tickets from Linear."""
    from arcane.plugins.builtin.linear_ingest import LinearIngestionPlugin

    project = project or os.path.basename(os.getcwd())
    plugin = LinearIngestionPlugin(team_id=team_id)
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    return json.dumps(result)


def handle_analyze(
    container: ServiceContainer,
    plugin_name: str,
    project: str | None = None,
) -> str:
    """Run an intelligence analysis plugin."""
    from arcane.services.intelligence import IntelligenceService

    project = project or os.path.basename(os.getcwd())
    svc = IntelligenceService(container)

    plugin: IntelligencePlugin
    if plugin_name == "ci_flakes":
        from arcane.plugins.builtin.ci_flakes import CIFlakeDetector

        plugin = CIFlakeDetector(artifact_repo=container.artifact_repo)
    elif plugin_name == "velocity":
        from arcane.plugins.builtin.velocity import VelocityTracker

        plugin = VelocityTracker(
            artifact_repo=container.artifact_repo,
            memory_repo=container.memory_repo,
            journey_repo=container.journey_repo,
        )
    else:
        return json.dumps({"error": f"Unknown analysis plugin: {plugin_name}"})

    result = svc.run_plugin(plugin, project=project)
    return json.dumps(result)
