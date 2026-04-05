"""Analysis commands — flakes and velocity."""

from __future__ import annotations

import os

import click

from arcane.cli._utils import create_container


@click.group()
def analyze() -> None:
    """Run intelligence analysis plugins."""


@analyze.command("flakes")
@click.option("--project", default=None, help="Project name")
def analyze_flakes(project: str | None) -> None:
    """Detect flaky CI runs."""
    from arcane.plugins.builtin.ci_flakes import CIFlakeDetector
    from arcane.services.intelligence import IntelligenceService

    project = project or os.path.basename(os.getcwd())
    with create_container() as container:
        plugin = CIFlakeDetector(artifact_repo=container.artifact_repo)
        result = IntelligenceService(container).run_plugin(plugin, project=project)

    if result["insights_created"] > 0:
        click.echo(f"CI flake analysis: {result['insights_created']} insight(s) created")
    else:
        click.echo("No CI flakes detected.")


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
