"""Journey commands — start, update, complete, list, show."""

from __future__ import annotations

import os

import click

from arcane.cli._utils import create_container


@click.group()
def journey() -> None:
    """Manage decision journeys."""


@journey.command("start")
@click.option("--title", required=True)
@click.option("--project", default=None)
@click.option("--linear-issue", default=None)
def journey_start(title: str, project: str | None, linear_issue: str | None) -> None:
    """Start tracking a decision journey."""
    from arcane.services.journey import JourneyService

    with create_container() as container:
        result = JourneyService(container).start(
            title=title, project=project, linear_issue_id=linear_issue
        )
    click.echo(f"Journey started: {result['title']} (id: {result['id'][:12]})")


@journey.command("update")
@click.argument("journey_id")
@click.option("--summary", default=None)
def journey_update(journey_id: str, summary: str | None) -> None:
    """Update a journey."""
    from arcane.services.journey import JourneyService

    with create_container() as container:
        updated = JourneyService(container).update(journey_id, summary=summary)
    click.echo("Updated." if updated else f"Journey {journey_id} not found.")


@journey.command("complete")
@click.argument("journey_id")
@click.option("--summary", default=None)
def journey_complete(journey_id: str, summary: str | None) -> None:
    """Complete a journey."""
    from arcane.services.journey import JourneyService

    with create_container() as container:
        completed = JourneyService(container).complete(journey_id, summary=summary)
    click.echo("Completed." if completed else f"Journey {journey_id} not found.")


@journey.command("list")
@click.option("--project", is_flag=True, default=False)
@click.option("--status", type=click.Choice(["active", "completed", "abandoned"]), default=None)
@click.option("--limit", default=20)
def journey_list(project: bool, status: str | None, limit: int) -> None:
    """List journeys."""
    from arcane.services.journey import JourneyService

    project_name = os.path.basename(os.getcwd()) if project else None
    with create_container() as container:
        journeys = JourneyService(container).list(project=project_name, status=status, limit=limit)

    if not journeys:
        click.echo("No journeys found.")
        return

    for j in journeys:
        status_icon = {"active": "+", "completed": "v", "abandoned": "x"}.get(j["status"], "?")
        click.echo(f"  [{status_icon}] {j['title']} ({j['id'][:12]}) — {j['project']}")


@journey.command("show")
@click.argument("journey_id")
def journey_show(journey_id: str) -> None:
    """Show a journey with linked entities."""
    from arcane.services.journey import JourneyService

    with create_container() as container:
        journey_data = JourneyService(container).show(journey_id)

    if not journey_data:
        click.echo(f"Journey {journey_id} not found.")
        return

    click.echo(f"\n{journey_data['title']}")
    click.echo(f"  Status: {journey_data['status']}")
    click.echo(f"  Project: {journey_data['project']}")
    click.echo(f"  Started: {journey_data['started_at'][:10]}")
    if journey_data.get("summary"):
        click.echo(f"  Summary: {journey_data['summary']}")

    memories = journey_data.get("linked_memories", [])
    if memories:
        click.echo(f"\n  Linked memories ({len(memories)}):")
        for item in memories:
            m = item["memory"]
            click.echo(f"    - [{item['relation']}] {m['title']}")

    artifacts = journey_data.get("linked_artifacts", [])
    if artifacts:
        click.echo(f"\n  Linked artifacts ({len(artifacts)}):")
        for item in artifacts:
            a = item["artifact"]
            click.echo(f"    - [{item['relation']}] {a['title']}")
