"""Memory commands — save, search, details, delete, context, reindex, stats, sessions."""

from __future__ import annotations

import os

import click

from arcane.cli._utils import create_container
from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput


@click.command()
def init() -> None:
    """Initialise the arcane vault."""
    from arcane.infra.config import get_home

    home = get_home()
    os.makedirs(os.path.join(home, "vault"), exist_ok=True)
    click.echo(f"Arcane vault initialised at {home}")


@click.command()
@click.option("--title", required=True, help="Title of the memory")
@click.option("--what", required=True, help="What happened or was learned")
@click.option("--why", default=None, help="Why it matters")
@click.option("--impact", default=None, help="Impact or consequences")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--category", type=click.Choice([c.value for c in Category]), default=None)
@click.option("--related-files", default="", help="Comma-separated file paths")
@click.option("--details", default=None, help="Extended details")
@click.option("--details-file", default=None, help="Path to details file")
@click.option("--source", default=None, help="Source agent")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link to a journey")
def save(
    title: str,
    what: str,
    why: str | None,
    impact: str | None,
    tags: str,
    category: str | None,
    related_files: str,
    details: str | None,
    details_file: str | None,
    source: str | None,
    project: str | None,
    journey_id: str | None,
) -> None:
    """Save a memory to the current session."""
    from arcane.services.memory import MemoryService

    project = project or os.path.basename(os.getcwd())
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    file_list = [f.strip() for f in related_files.split(",") if f.strip()] if related_files else []

    if details and details_file:
        raise click.UsageError("Use either --details or --details-file, not both.")

    resolved_details = details
    if details_file:
        try:
            with open(details_file) as f:
                resolved_details = f.read()
        except OSError as e:
            raise click.ClickException(f"Failed to read '{details_file}': {e}") from e

    raw = RawMemoryInput(
        title=title,
        what=what,
        why=why,
        impact=impact,
        tags=tag_list,
        category=category,
        related_files=file_list,
        details=resolved_details,
        source=source,
        journey_id=journey_id,
    )

    with create_container() as container:
        result = MemoryService(container).save(raw, project=project)

    click.echo(f"Saved: {title} (id: {result['id']})")
    click.echo(f"File: {result['file_path']}")
    for warning in result.get("warnings", []):
        click.echo(f"Warning: {warning}")


@click.command()
@click.argument("query")
@click.option("--limit", default=5)
@click.option("--project", is_flag=True, default=False, help="Filter to current project")
@click.option("--source", default=None)
def search(query: str, limit: int, project: bool, source: str | None) -> None:
    """Search memories."""
    from arcane.services.memory import MemoryService

    project_name = os.path.basename(os.getcwd()) if project else None

    with create_container() as container:
        results = MemoryService(container).search(query, limit=limit, project=project_name, source=source)

    if not results:
        click.echo("No results found.")
        return

    click.echo(f"\n Results ({len(results)} found) ")
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        click.echo(f"\n [{i}] {r['title']} (score: {score:.2f})")
        click.echo(f"     {r.get('category', '')} | {r.get('created_at', '')[:10]} | {r.get('project', '')}")
        click.echo(f"     What: {r['what']}")
        if r.get("why"):
            click.echo(f"     Why: {r['why']}")
        if r.get("impact"):
            click.echo(f"     Impact: {r['impact']}")
        if r.get("has_details"):
            click.echo(f"     Details: available (use `arcane details {r['id'][:12]}`)")


@click.command()
@click.argument("memory_id")
def details(memory_id: str) -> None:
    """Fetch full details for a memory."""
    from arcane.services.memory import MemoryService

    with create_container() as container:
        detail = MemoryService(container).get_details(memory_id)

    if not detail:
        click.echo(f"No details found for {memory_id}")
        return
    click.echo(detail["body"])


@click.command()
@click.argument("memory_id")
def delete(memory_id: str) -> None:
    """Delete a memory by ID or prefix."""
    from arcane.services.memory import MemoryService

    with create_container() as container:
        deleted = MemoryService(container).delete(memory_id)

    click.echo(f"Deleted memory {memory_id}" if deleted else f"No memory found for {memory_id}")


@click.command()
@click.option("--project", is_flag=True, default=False)
@click.option("--source", default=None)
@click.option("--limit", default=10)
@click.option("--query", default=None)
def context(project: bool, source: str | None, limit: int, query: str | None) -> None:
    """Output memory context for agent injection."""
    from arcane.services.memory import MemoryService

    project_name = os.path.basename(os.getcwd()) if project else None

    with create_container() as container:
        results, total = MemoryService(container).get_context(
            limit=limit, project=project_name, source=source, query=query
        )

    if not results:
        click.echo("No memories found.")
        return

    click.echo(f"Available memories ({total} total, showing {len(results)}):")
    for r in results:
        date_str = r.get("created_at", "")[:10]
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(date_str)
            date_display = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_display = date_str

        title = r.get("title", "Untitled")
        cat = r.get("category", "")
        tags_list = r.get("tags", [])  # already list[str] from repo

        cat_part = f" [{cat}]" if cat else ""
        tags_part = f" [{','.join(tags_list)}]" if tags_list else ""
        click.echo(f"- [{date_display}] {title}{cat_part}{tags_part}")

    click.echo("Use `arcane search <query>` for full details on any memory.")


@click.command()
def reindex() -> None:
    """Rebuild vector index."""
    from arcane.services.memory import MemoryService

    with create_container() as container:
        total = container.memory_repo.count()
        if total == 0:
            click.echo("No memories to reindex.")
            return

        click.echo(f"Reindexing {total} memories...")

        def progress(current: int, count: int) -> None:
            click.echo(f"  {current}/{count}", nl=(current == count))
            if current < count:
                click.echo("\r", nl=False)

        result = MemoryService(container).reindex(progress_callback=progress)

    click.echo(f"Re-indexed {result['count']} memories ({result['model']}, {result['dim']} dims)")


@click.command()
def stats() -> None:
    """Show database statistics."""
    with create_container() as container:
        click.echo("Arcane statistics:")
        click.echo(f"  Memories:      {container.memory_repo.count()}")
        click.echo(f"  Journeys:      {container.journey_repo.count()}")
        click.echo(f"  Artifacts:     {container.artifact_repo.count()}")
        click.echo(f"  Relationships: {container.relationship_repo.count()}")
        click.echo(f"  Insights:      {container.insight_repo.count()}")
        click.echo(f"  Home:          {container.home}")


@click.command()
@click.option("--limit", default=10)
@click.option("--project", default=None)
def sessions(limit: int, project: str | None) -> None:
    """List recent sessions."""
    with create_container() as container:
        vault = container.vault_dir

    session_files = []
    if os.path.exists(vault):
        for proj_dir in sorted(os.listdir(vault)):
            proj_path = os.path.join(vault, proj_dir)
            if not os.path.isdir(proj_path) or proj_dir.startswith("."):
                continue
            if project and proj_dir != project:
                continue
            for f in sorted(os.listdir(proj_path), reverse=True):
                if f.endswith("-session.md"):
                    session_files.append((proj_dir, f))

    if not session_files:
        click.echo("No sessions found.")
        return

    click.echo("\nSessions:")
    for proj, fname in session_files[:limit]:
        date_str = fname.replace("-session.md", "")
        click.echo(f"  {date_str} | {proj}")
