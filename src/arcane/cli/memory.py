"""Memory commands — save, search, details, delete, context, reindex, stats, sessions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click

from arcane.cli._utils import create_container
from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput
from arcane.domain.scope import READ_SCOPES, ReadScope, plan_read, resolve_write_scope


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
@click.option("--supersedes", default=None, help="ID or prefix of an earlier memory this one replaces")
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
    supersedes: str | None,
) -> None:
    """Save a memory to the current session."""
    from arcane.services.memory import MemoryService

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
        supersedes=supersedes,
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
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Search from the current project: its own memories, then the org's other projects when it has "
    "fewer than 3 matches. Without it, every memory is searched.",
)
@click.option("--source", default=None)
@click.option(
    "--scope",
    type=click.Choice(READ_SCOPES),
    default=None,
    help="project: this project only. org: org-level memories only. global: global memories only. "
    "all: every project in every org. Implies --project.",
)
def search(query: str, limit: int, project: bool, source: str | None, scope: ReadScope | None) -> None:
    """Search memories."""
    from arcane.services.memory import MemoryService

    plan = None
    with create_container() as container:
        if project or scope:
            resolved = resolve_write_scope(None, container.config)
            plan = plan_read(scope, resolved.org, resolved.project)
            results = MemoryService(container).search(
                query,
                limit=limit,
                project=plan.project,
                source=source,
                org=plan.org,
                include_org=plan.include_org,
                include_global=plan.include_global,
                reach=plan.reach,
            )
        else:
            results = MemoryService(container).search(query, limit=limit, source=source)

    if not results:
        click.echo("No results found." + (f" {plan.nothing_found()}" if plan and plan.nothing_found() else ""))
        return

    click.echo(f"\n Results ({len(results)} found) ")
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        click.echo(f"\n [{i}] {r['title']} (score: {score:.2f})")
        meta = (r.get("category"), (r.get("created_at") or "")[:10], r.get("project"), r.get("org"))
        click.echo("     " + " | ".join(part for part in meta if part))
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

    with create_container() as container:
        if project:
            resolved = resolve_write_scope(None, container.config)
            project_name, org = resolved.project, resolved.org
        else:
            project_name, org = None, None
        results, total = MemoryService(container).get_context(
            limit=limit, project=project_name, source=source, query=query, org=org
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
        # Context can reach into the org's other projects, so say which one each memory is from.
        project_part = f" ({r['project']})" if r.get("project") else ""
        click.echo(f"- [{date_display}] {title}{project_part}{cat_part}{tags_part}")

    click.echo("Use `arcane search <query>` for full details on any memory.")


@click.command(name="projects")
def projects() -> None:
    """List distinct projects with memory counts."""
    with create_container() as container:
        rows = container.memory_repo.list_projects()

    if not rows:
        click.echo("No projects found.")
        return

    click.echo("\nProjects:")
    for r in rows:
        org_part = f" ({r['org']})" if r.get("org") else ""
        click.echo(f"  {r['cnt']:5d}  {r['project'] or '<no project>'}{org_part}")


@click.command(name="merge-projects")
@click.argument("src")
@click.argument("dest")
@click.option("--org", default=None, help="Org that owns SRC. Required when several orgs have a project of that name.")
@click.option("--apply", "apply_", is_flag=True, default=False, help="Write the change (default: dry run).")
def merge_projects(src: str, dest: str, org: str | None, apply_: bool) -> None:
    """Merge one org's memories, journeys, artifacts and insights from project SRC into DEST.

    SRC must match the stored project string exactly; DEST is canonicalized
    (normalised, aliases applied) so merges always heal towards the canonical
    name. Only one org's rows move: when several orgs have a project
    called SRC, --org says which. Dry-run by default — pass --apply to commit,
    which first backs up the store.
    """
    from arcane.domain.scope import canonicalize_project, slugify, validate_org

    with create_container() as container:
        dest_canon = canonicalize_project(dest, container.config.projects.aliases)
        if src == dest_canon:
            raise click.UsageError("Source and destination are the same project — nothing to merge.")
        if dest_canon != dest:
            click.echo(f"Destination canonicalized: '{dest}' → '{dest_canon}'")

        # A project may hold only journeys, artifacts or insights (its memories merged
        # earlier, or never saved), so its owners come from all four tables.
        repos: dict[str, Any] = {
            "memories": container.memory_repo,
            "journeys": container.journey_repo,
            "artifacts": container.artifact_repo,
            "insights": container.insight_repo,
        }
        held: dict[str, dict[str, int]] = {
            "memories": {r["org"]: r["cnt"] for r in container.memory_repo.list_projects() if r["project"] == src}
        }
        for name in ("journeys", "artifacts", "insights"):
            held[name] = repos[name].count_by_org(src)
        owners = {org_name for counts in held.values() for org_name in counts}
        if org is not None:
            try:
                org = validate_org(slugify(org))
            except ValueError as exc:
                raise click.BadParameter(str(exc), param_hint="--org") from exc
            owners = {org}
        elif len(owners) > 1:
            listed = ", ".join(
                f"{name or '<no org>'} ({sum(counts.get(name, 0) for counts in held.values())})"
                for name in sorted(owners)
            )
            raise click.UsageError(f"Project '{src}' exists in several orgs: {listed}. Pass --org to choose one.")
        source_org = next(iter(owners), None)
        where = f"'{src}'" + (f" in org {source_org or '<no org>'}" if source_org is not None else "")
        counts = {name: held[name].get(source_org, 0) if source_org is not None else 0 for name in repos}
        stays = repos["artifacts"].count_collisions(src, dest_canon, org=source_org) if source_org is not None else 0
        collision_note = (
            f" {stays} artifacts stay in '{src}': '{dest_canon}' already has the same type and external id."
            if stays
            else ""
        )

        if not apply_:
            listed = ", ".join(f"{n} {name}" for name, n in counts.items())
            click.echo(
                f"Dry run: would move {listed} from {where} into '{dest_canon}'.{collision_note} "
                "Pass --apply to commit."
            )
            return
        if source_org is None:
            click.echo(f"Moved 0 memories from {where} into '{dest_canon}'.")
            return

        from arcane.services.backup import BackupError, create_backup

        # The home of the store this command opened, not the default home, so the
        # backup is always of the database about to change. An in-memory store has none.
        # It goes beside, not in, the `arcane backup` folder and never rotates, so a
        # merge cannot push out a backup someone took on purpose.
        db_path = container.db.db_path
        if db_path != ":memory:":
            home = os.path.dirname(os.path.abspath(db_path))
            try:
                backup = create_backup(home, os.path.join(home, "backups", "pre-merge"), keep=0)
            except BackupError as exc:
                raise click.ClickException(f"Backup failed, nothing moved: {exc}") from exc
            click.echo(f"Backed up to {backup.path}")

        # One transaction: a failure part way leaves every table as it was.
        with container.db.transaction():
            moved = {name: repo.reassign_project(src, dest_canon, org=source_org) for name, repo in repos.items()}
        listed = ", ".join(f"{n} {name}" for name, n in moved.items())
        left = counts["artifacts"] - moved["artifacts"]
        note = (
            f" {left} artifacts stayed in '{src}': '{dest_canon}' already has the same type and external id."
            if left
            else ""
        )
        click.echo(f"Moved {listed} from {where} into '{dest_canon}'.{note}")


@click.command()
def reindex() -> None:
    """Rebuild vector index."""
    from arcane.services.memory import MemoryService

    with create_container() as container:
        if container.config.embedding.provider == "none":
            raise click.ClickException("Embeddings are disabled (embedding.provider: none), so there is no index.")
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
    for path in Path(vault).rglob("*-session.md"):
        relative = path.relative_to(vault)
        parts = relative.parts[:-1]
        project_name = parts[-1] if parts else ""
        if project and project_name != project:
            continue
        session_files.append(("/".join(parts), path.name))
    session_files.sort(key=lambda item: (item[1], item[0]), reverse=True)

    if not session_files:
        click.echo("No sessions found.")
        return

    click.echo("\nSessions:")
    for proj, fname in session_files[:limit]:
        date_str = fname.replace("-session.md", "")
        click.echo(f"  {date_str} | {proj}")
