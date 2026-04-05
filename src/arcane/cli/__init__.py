"""Arcane CLI — command groups assembled from sub-modules."""

from __future__ import annotations

import click

from arcane.cli.analyze import analyze
from arcane.cli.config import config
from arcane.cli.draft import draft
from arcane.cli.ingest import ingest
from arcane.cli.journey import journey
from arcane.cli.memory import context, delete, details, init, reindex, save, search, sessions, stats
from arcane.cli.migrate import migrate
from arcane.cli.relationship import link, trace


@click.group()
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
main.add_command(sessions)
main.add_command(journey)
main.add_command(link)
main.add_command(trace)
main.add_command(migrate)
main.add_command(config)
main.add_command(ingest)
main.add_command(analyze)
main.add_command(draft)


@main.command()
def mcp() -> None:
    """Start the Arcane MCP server (stdio transport)."""
    import asyncio
    from arcane.mcp_server.server import run_server
    asyncio.run(run_server())
