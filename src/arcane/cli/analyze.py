"""Analysis commands — velocity and health."""

from __future__ import annotations

import os

import click

from arcane.cli._utils import create_container


@click.group()
def analyze() -> None:
    """Run intelligence analysis plugins."""


@analyze.command("health")
@click.option("--project", default=None, help="Project to attach the insights to")
def analyze_health(project: str | None) -> None:
    """Audit store health — fragmentation, orphans, duplicates, journey hygiene."""
    from arcane.plugins.builtin.health_audit import HealthAuditor

    project = project or os.path.basename(os.getcwd())
    with create_container() as container:
        plugin = HealthAuditor(
            memory_repo=container.memory_repo,
            journey_repo=container.journey_repo,
            aliases=container.config.projects.aliases,
        )
        insights = plugin.analyze(project=project)
        for insight in insights:
            container.insight_repo.insert(insight)

    for insight in insights:
        marker = "!" if insight["severity"] != "info" else "-"
        click.echo(f"\n{marker} [{insight['severity']}] {insight['title']}")
        click.echo(insight["body"])


@analyze.command("velocity")
@click.option("--project", default=None, help="Project name")
def analyze_velocity(project: str | None) -> None:
    """Generate engineering velocity summary."""
    from arcane.plugins.builtin.velocity import VelocityTracker
    from arcane.services.intelligence import IntelligenceService

    project = project or os.path.basename(os.getcwd())
    with create_container() as container:
        plugin = VelocityTracker(
            artifact_repo=container.artifact_repo,
            memory_repo=container.memory_repo,
            journey_repo=container.journey_repo,
        )
        result = IntelligenceService(container).run_plugin(plugin, project=project)

    click.echo(f"Velocity analysis: {result['insights_created']} insight(s) created")
