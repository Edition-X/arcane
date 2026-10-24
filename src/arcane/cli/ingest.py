"""Ingestion commands — git, gha, linear."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import click

from arcane.cli._plugins import PluginGroup, list_plugins
from arcane.cli._utils import create_container
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.plugins.protocols import IngestionError
from arcane.plugins.registry import create_plugin

if TYPE_CHECKING:
    from arcane.plugins.protocols import IngestionPlugin
    from arcane.services.ingestion import IngestionService


def _run(
    svc: IngestionService,
    plugin: IngestionPlugin,
    project: str | None,
    journey_id: str | None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    try:
        return svc.run_plugin(plugin, project=project, journey_id=journey_id, repo_path=repo_path)
    except (IdentifierResolutionError, IngestionError) as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(cls=PluginGroup, kind="ingestion", invoke_without_command=True)
@click.option("--list", "show_plugins", is_flag=True, help="List installed entry-point plugins.")
@click.pass_context
def ingest(ctx: click.Context, show_plugins: bool) -> None:
    """Ingest data from external sources."""
    if show_plugins:
        list_plugins("ingestion")
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@ingest.command("git")
@click.option("--project", default=None, help="Project name")
@click.option("--repo-path", default=None, help="Path to git repo (default: cwd)")
@click.option("--max-count", default=100, help="Max commits to ingest")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_git(project: str | None, repo_path: str | None, max_count: int, journey_id: str | None) -> None:
    """Ingest commits from a git repository."""
    from arcane.services.ingestion import IngestionService

    with create_container() as container:
        plugin = create_plugin(
            "ingestion", "git", container, {"repo_path": repo_path or os.getcwd(), "max_count": max_count}
        )
        result = _run(IngestionService(container), plugin, project, journey_id, repo_path)

    click.echo(f"Git ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("gha")
@click.option("--owner", required=True, help="GitHub repo owner")
@click.option("--repo", required=True, help="GitHub repo name")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_gha(owner: str, repo: str, project: str | None, journey_id: str | None) -> None:
    """Ingest CI runs from GitHub Actions."""
    from arcane.services.ingestion import IngestionService

    with create_container() as container:
        plugin = create_plugin("ingestion", "github_actions", container, {"owner": owner, "repo": repo})
        result = _run(IngestionService(container), plugin, project, journey_id)

    click.echo(f"GHA ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("linear")
@click.option("--team", required=True, help="Linear team ID")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_linear(team: str, project: str | None, journey_id: str | None) -> None:
    """Ingest tickets from Linear."""
    from arcane.services.ingestion import IngestionService

    with create_container() as container:
        plugin = create_plugin("ingestion", "linear", container, {"team_id": team})
        result = _run(IngestionService(container), plugin, project, journey_id)

    click.echo(f"Linear ingestion: {result['ingested']} ingested, {result['skipped']} skipped")
