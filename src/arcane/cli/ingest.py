"""Ingestion commands — git, gha, linear."""

from __future__ import annotations

import os

import click

from arcane.cli._utils import create_container


@click.group()
def ingest() -> None:
    """Ingest data from external sources."""


@ingest.command("git")
@click.option("--project", default=None, help="Project name")
@click.option("--repo-path", default=None, help="Path to git repo (default: cwd)")
@click.option("--max-count", default=100, help="Max commits to ingest")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_git(project: str | None, repo_path: str | None, max_count: int, journey_id: str | None) -> None:
    """Ingest commits from a git repository."""
    from arcane.plugins.builtin.git_ingest import GitIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = GitIngestionPlugin(repo_path=repo_path or os.getcwd(), max_count=max_count)

    with create_container() as container:
        result = IngestionService(container).run_plugin(plugin, project=project, journey_id=journey_id)

    click.echo(f"Git ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("gha")
@click.option("--owner", required=True, help="GitHub repo owner")
@click.option("--repo", required=True, help="GitHub repo name")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_gha(owner: str, repo: str, project: str | None, journey_id: str | None) -> None:
    """Ingest CI runs from GitHub Actions."""
    from arcane.plugins.builtin.gha_ingest import GHAIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = GHAIngestionPlugin(owner=owner, repo=repo)

    with create_container() as container:
        result = IngestionService(container).run_plugin(plugin, project=project, journey_id=journey_id)

    click.echo(f"GHA ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("linear")
@click.option("--team", required=True, help="Linear team ID")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_linear(team: str, project: str | None, journey_id: str | None) -> None:
    """Ingest tickets from Linear."""
    from arcane.plugins.builtin.linear_ingest import LinearIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = LinearIngestionPlugin(team_id=team)

    with create_container() as container:
        result = IngestionService(container).run_plugin(plugin, project=project, journey_id=journey_id)

    click.echo(f"Linear ingestion: {result['ingested']} ingested, {result['skipped']} skipped")
