"""Analysis commands — velocity, health and usage."""

from __future__ import annotations

import click

from arcane.cli._plugins import PluginGroup, list_plugins
from arcane.cli._utils import create_container
from arcane.plugins.registry import create_plugin


@click.group(cls=PluginGroup, kind="intelligence", invoke_without_command=True)
@click.option("--list", "show_plugins", is_flag=True, help="List installed entry-point plugins.")
@click.pass_context
def analyze(ctx: click.Context, show_plugins: bool) -> None:
    """Run intelligence analysis plugins."""
    if show_plugins:
        list_plugins("intelligence")
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@analyze.command("health")
@click.option("--project", default=None, help="Project to attach the insights to")
def analyze_health(project: str | None) -> None:
    """Audit store health — fragmentation, orphans, duplicates, journey hygiene."""

    with create_container() as container:
        plugin = create_plugin("intelligence", "health", container)
        from arcane.services.intelligence import IntelligenceService

        result = IntelligenceService(container).run_plugin(plugin, project=project)
        insights = container.insight_repo.list_all(
            project=result["project"], org=result["org"], limit=result["insights_created"]
        )

    for insight in insights:
        marker = "!" if insight["severity"] != "info" else "-"
        click.echo(f"\n{marker} [{insight['severity']}] {insight['title']}")
        click.echo(insight["body"])


@analyze.command("usage")
@click.option("--days", default=30, show_default=True, help="Window to report on")
@click.option("--project", default=None, help="Project to attach the insights to")
def analyze_usage(days: int, project: str | None) -> None:
    """Report what agents recall — lookups, empty searches, unused memories."""
    from arcane.services.intelligence import IntelligenceService

    with create_container() as container:
        plugin = create_plugin("intelligence", "usage", container, {"days": days})
        result = IntelligenceService(container).run_plugin(plugin, project=project)
        insights = container.insight_repo.list_all(
            project=result["project"], org=result["org"], limit=result["insights_created"]
        )

    for insight in reversed(insights):
        marker = "!" if insight["severity"] != "info" else "-"
        click.echo(f"\n{marker} [{insight['severity']}] {insight['title']}")
        click.echo(insight["body"])


@analyze.command("velocity")
@click.option("--project", default=None, help="Project name")
def analyze_velocity(project: str | None) -> None:
    """Generate engineering velocity summary."""
    from arcane.services.intelligence import IntelligenceService

    with create_container() as container:
        plugin = create_plugin("intelligence", "velocity", container)
        result = IntelligenceService(container).run_plugin(plugin, project=project)

    click.echo(f"Velocity analysis: {result['insights_created']} insight(s) created")
