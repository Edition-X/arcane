"""Draft commands — blog and ADR generation."""

from __future__ import annotations

import click

from arcane.cli._utils import create_container


@click.group()
def draft() -> None:
    """Generate structured content briefs."""


@draft.command("blog")
@click.option("--journey-id", default=None, help="Journey to generate brief from")
@click.option("--project", default=None, help="Project for memory-based brief")
def draft_blog(journey_id: str | None, project: str | None) -> None:
    """Generate a structured blog brief."""
    from arcane.plugins.builtin.blog_gen import BlogGenerator

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
            context["memories"] = container.memory_repo.list_recent(limit=20, project=project)
            context["project"] = project
        else:
            click.echo("Provide --journey-id or --project.")
            return

        brief = BlogGenerator().generate(context)

    click.echo(brief)


@draft.command("adr")
@click.argument("memory_id")
def draft_adr(memory_id: str) -> None:
    """Generate a structured ADR from a decision memory."""
    from arcane.plugins.builtin.adr_gen import ADRGenerator

    with create_container() as container:
        mem = container.memory_repo.get(memory_id)
        if not mem:
            click.echo(f"Memory {memory_id} not found.")
            return
        detail = container.memory_repo.get_details(memory_id)
        detail_body = detail["body"] if detail else ""
        adr = ADRGenerator().generate(context={"memory": mem, "details": detail_body})

    click.echo(adr)
