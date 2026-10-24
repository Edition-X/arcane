"""Draft commands — blog and ADR generation."""

from __future__ import annotations

import click

from arcane.cli._plugins import PluginGroup, list_plugins
from arcane.cli._utils import create_container
from arcane.domain.scope import resolve_write_scope
from arcane.infra.redaction import redact
from arcane.plugins.registry import create_plugin
from arcane.services.memory import MemoryService


@click.group(cls=PluginGroup, kind="content", invoke_without_command=True)
@click.option("--list", "show_plugins", is_flag=True, help="List installed entry-point plugins.")
@click.pass_context
def draft(ctx: click.Context, show_plugins: bool) -> None:
    """Generate structured content briefs."""
    if show_plugins:
        list_plugins("content")
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@draft.command("blog")
@click.option("--journey-id", default=None, help="Journey to generate brief from")
@click.option("--project", default=None, help="Project for memory-based brief")
def draft_blog(journey_id: str | None, project: str | None) -> None:
    """Generate a structured blog brief."""

    with create_container() as container:
        context: dict = {}
        if journey_id:
            from arcane.services.journey import JourneyService

            journey_data = JourneyService(container).show(journey_id)
            if not journey_data:
                click.echo(f"Journey {journey_id} not found.")
                return
            context["journey"] = journey_data
        elif project:
            scope = resolve_write_scope(project, container.config)
            context["memories"], _ = MemoryService(container).get_context(
                limit=20, project=scope.project, org=scope.org
            )
            context["project"] = project
        else:
            click.echo("Provide --journey-id or --project.")
            return

        brief = redact(create_plugin("content", "blog", container).generate(context), container.ignore_patterns)

    click.echo(brief)


@draft.command("adr")
@click.argument("memory_id")
def draft_adr(memory_id: str) -> None:
    """Generate a structured ADR from a decision memory."""

    with create_container() as container:
        mem = container.memory_repo.get(memory_id)
        if not mem:
            click.echo(f"Memory {memory_id} not found.")
            return
        detail = container.memory_repo.get_details(memory_id)
        detail_body = detail["body"] if detail else ""
        adr = redact(
            create_plugin("content", "adr", container).generate(context={"memory": mem, "details": detail_body}),
            container.ignore_patterns,
        )

    click.echo(adr)
