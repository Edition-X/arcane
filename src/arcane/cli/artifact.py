"""Artifact commands — search and inspect ingested external records."""

from __future__ import annotations

import json

import click

from arcane.cli._utils import create_container


@click.group()
def artifact() -> None:
    """Search and inspect ingested artifacts."""


@artifact.command("search")
@click.argument("query")
@click.option("--project", default=None)
@click.option("--type", "artifact_type", default=None)
@click.option("--limit", default=10)
def artifact_search(query: str, project: str | None, artifact_type: str | None, limit: int) -> None:
    """Search artifact titles, IDs, and ingested raw content."""
    with create_container() as container:
        artifacts = container.artifact_repo.fts_search(query, project=project, artifact_type=artifact_type, limit=limit)
    if not artifacts:
        click.echo("No artifacts found.")
        return
    for item in artifacts:
        click.echo(f"[{item['artifact_type']}] {item['title']} ({item['id'][:12]})")


@artifact.command("show")
@click.argument("artifact_id")
def artifact_show(artifact_id: str) -> None:
    """Show complete artifact data by ID or prefix."""
    with create_container() as container:
        item = container.artifact_repo.get(artifact_id)
    if not item:
        click.echo(f"Artifact {artifact_id} not found.")
        return
    raw_data = item.get("raw_data")
    if isinstance(raw_data, str):
        try:
            item["raw_data"] = json.loads(raw_data)
        except json.JSONDecodeError:
            pass
    click.echo(json.dumps(item, indent=2, sort_keys=True))
