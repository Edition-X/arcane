"""Arcane CLI — command groups assembled from sub-modules."""

from __future__ import annotations

from typing import Any

import click

from arcane import __version__
from arcane.cli.analyze import analyze
from arcane.cli.artifact import artifact
from arcane.cli.backup import backup
from arcane.cli.config import config
from arcane.cli.draft import draft
from arcane.cli.ingest import ingest
from arcane.cli.journey import journey
from arcane.cli.memory import (
    context,
    delete,
    details,
    init,
    merge_projects,
    projects,
    reindex,
    save,
    search,
    sessions,
    stats,
)
from arcane.cli.migrate import migrate
from arcane.cli.relationship import link, trace
from arcane.cli.report import export, report


class ArcaneGroup(click.Group):
    """Report a broken ``config.yaml`` as a message rather than a traceback.

    Every command opens a store, so the one place that can catch this for all
    of them is the group itself.
    """

    def invoke(self, ctx: click.Context) -> Any:
        from arcane.infra.config import ConfigError

        try:
            return super().invoke(ctx)
        except ConfigError as exc:
            raise click.ClickException(str(exc)) from exc


@click.group(cls=ArcaneGroup)
@click.version_option(__version__, prog_name="arcane")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """Arcane — unified engineering intelligence."""
    from arcane.infra.logging import configure_logging

    configure_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


main.add_command(init)
main.add_command(save)
main.add_command(search)
main.add_command(details)
main.add_command(delete)
main.add_command(context)
main.add_command(reindex)
main.add_command(stats)
main.add_command(backup)
main.add_command(sessions)
main.add_command(projects)
main.add_command(merge_projects)
main.add_command(journey)
main.add_command(link)
main.add_command(trace)
main.add_command(migrate)
main.add_command(config)
main.add_command(ingest)
main.add_command(analyze)
main.add_command(artifact)
main.add_command(draft)
main.add_command(report)
main.add_command(export)


@main.command()
def mcp() -> None:
    """Start the Arcane MCP server (stdio transport)."""
    import asyncio

    from arcane.mcp_server.server import run_server

    asyncio.run(run_server())
