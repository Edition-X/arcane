"""CLI commands for Arcane."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

import click
import yaml

from arcane.domain.enums import Category
from arcane.domain.models import RawMemoryInput
from arcane.infra.config import (
    clear_persisted_home,
    get_home,
    load_config,
    resolve_home,
    set_persisted_home,
)
from arcane.services.container import create_container


def _redact_api_keys(data: dict) -> dict:
    for section in ("embedding",):
        cfg = data.get(section)
        if isinstance(cfg, dict) and cfg.get("api_key"):
            cfg["api_key"] = "<redacted>"
    return data


@click.group()
def main():
    """Arcane — unified engineering intelligence."""
    pass


# ── Core memory commands (EchoVault-compatible) ────────────────────────────


@main.command()
def init():
    """Initialize the arcane vault."""
    home = get_home()
    os.makedirs(os.path.join(home, "vault"), exist_ok=True)
    click.echo(f"Arcane vault initialized at {home}")


@main.command()
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
def save(title, what, why, impact, tags, category, related_files, details, details_file, source, project, journey_id):
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
        title=title, what=what, why=why, impact=impact, tags=tag_list,
        category=category, related_files=file_list, details=resolved_details,
        source=source, journey_id=journey_id,
    )

    container = create_container()
    svc = MemoryService(container)
    result = svc.save(raw, project=project)
    container.close()

    click.echo(f"Saved: {title} (id: {result['id']})")
    click.echo(f"File: {result['file_path']}")
    for warning in result.get("warnings", []):
        click.echo(f"Warning: {warning}")


@main.command()
@click.argument("query")
@click.option("--limit", default=5)
@click.option("--project", is_flag=True, default=False, help="Filter to current project")
@click.option("--source", default=None)
def search(query, limit, project, source):
    """Search memories."""
    from arcane.services.memory import MemoryService

    project_name = os.path.basename(os.getcwd()) if project else None

    container = create_container()
    svc = MemoryService(container)
    results = svc.search(query, limit=limit, project=project_name, source=source)
    container.close()

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


@main.command()
@click.argument("memory_id")
def details(memory_id):
    """Fetch full details for a memory."""
    from arcane.services.memory import MemoryService

    container = create_container()
    svc = MemoryService(container)
    detail = svc.get_details(memory_id)
    container.close()

    if not detail:
        click.echo(f"No details found for {memory_id}")
        return
    click.echo(detail["body"])


@main.command()
@click.argument("memory_id")
def delete(memory_id):
    """Delete a memory by ID or prefix."""
    from arcane.services.memory import MemoryService

    container = create_container()
    svc = MemoryService(container)
    deleted = svc.delete(memory_id)
    container.close()

    click.echo(f"Deleted memory {memory_id}" if deleted else f"No memory found for {memory_id}")


@main.command()
@click.option("--project", is_flag=True, default=False)
@click.option("--source", default=None)
@click.option("--limit", default=10)
@click.option("--query", default=None)
def context(project, source, limit, query):
    """Output memory context for agent injection."""
    from arcane.services.memory import MemoryService

    project_name = os.path.basename(os.getcwd()) if project else None

    container = create_container()
    svc = MemoryService(container)
    results, total = svc.get_context(limit=limit, project=project_name, source=source, query=query)
    container.close()

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
        tags_raw = r.get("tags", "")
        if isinstance(tags_raw, str) and tags_raw:
            try:
                tags_list = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags_list = []
        else:
            tags_list = tags_raw if isinstance(tags_raw, list) else []

        cat_part = f" [{cat}]" if cat else ""
        tags_part = f" [{','.join(tags_list)}]" if tags_list else ""
        click.echo(f"- [{date_display}] {title}{cat_part}{tags_part}")

    click.echo('Use `arcane search <query>` for full details on any memory.')


@main.command()
def reindex():
    """Rebuild vector index."""
    from arcane.services.memory import MemoryService

    container = create_container()
    svc = MemoryService(container)
    total = container.memory_repo.count()

    if total == 0:
        click.echo("No memories to reindex.")
        container.close()
        return

    click.echo(f"Reindexing {total} memories...")

    def progress(current, count):
        click.echo(f"  {current}/{count}", nl=(current == count))
        if current < count:
            click.echo("\r", nl=False)

    result = svc.reindex(progress_callback=progress)
    container.close()

    click.echo(f"Re-indexed {result['count']} memories ({result['model']}, {result['dim']} dims)")


# ── Journey commands ───────────────────────────────────────────────────────


@main.group()
def journey():
    """Manage decision journeys."""
    pass


@journey.command("start")
@click.option("--title", required=True)
@click.option("--project", default=None)
@click.option("--linear-issue", default=None)
def journey_start(title, project, linear_issue):
    """Start tracking a decision journey."""
    from arcane.services.journey import JourneyService

    container = create_container()
    svc = JourneyService(container)
    result = svc.start(title=title, project=project, linear_issue_id=linear_issue)
    container.close()
    click.echo(f"Journey started: {result['title']} (id: {result['id'][:12]})")


@journey.command("update")
@click.argument("journey_id")
@click.option("--summary", default=None)
def journey_update(journey_id, summary):
    """Update a journey."""
    from arcane.services.journey import JourneyService

    container = create_container()
    svc = JourneyService(container)
    updated = svc.update(journey_id, summary=summary)
    container.close()
    click.echo("Updated." if updated else f"Journey {journey_id} not found.")


@journey.command("complete")
@click.argument("journey_id")
@click.option("--summary", default=None)
def journey_complete(journey_id, summary):
    """Complete a journey."""
    from arcane.services.journey import JourneyService

    container = create_container()
    svc = JourneyService(container)
    completed = svc.complete(journey_id, summary=summary)
    container.close()
    click.echo("Completed." if completed else f"Journey {journey_id} not found.")


@journey.command("list")
@click.option("--project", is_flag=True, default=False)
@click.option("--status", type=click.Choice(["active", "completed", "abandoned"]), default=None)
@click.option("--limit", default=20)
def journey_list(project, status, limit):
    """List journeys."""
    from arcane.services.journey import JourneyService

    project_name = os.path.basename(os.getcwd()) if project else None
    container = create_container()
    svc = JourneyService(container)
    journeys = svc.list(project=project_name, status=status, limit=limit)
    container.close()

    if not journeys:
        click.echo("No journeys found.")
        return

    for j in journeys:
        status_icon = {"active": "+", "completed": "v", "abandoned": "x"}.get(j["status"], "?")
        click.echo(f"  [{status_icon}] {j['title']} ({j['id'][:12]}) — {j['project']}")


@journey.command("show")
@click.argument("journey_id")
def journey_show(journey_id):
    """Show a journey with linked entities."""
    from arcane.services.journey import JourneyService

    container = create_container()
    svc = JourneyService(container)
    journey_data = svc.show(journey_id)
    container.close()

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


# ── Relationship commands ──────────────────────────────────────────────────


@main.command()
@click.argument("source")
@click.argument("target")
@click.option(
    "--relation", required=True,
    type=click.Choice(["led_to", "informed_by", "resulted_in", "part_of", "supersedes", "references"]),
)
@click.option("--source-type", default="memory")
@click.option("--target-type", default="journey")
def link(source, target, relation, source_type, target_type):
    """Create a relationship between entities."""
    from arcane.domain.enums import RelationType
    from arcane.domain.models import Relationship

    container = create_container()
    rel = Relationship(
        source_type=source_type, source_id=source,
        target_type=target_type, target_id=target,
        relation=RelationType(relation),
    )
    container.relationship_repo.insert(rel.model_dump())
    container.close()
    click.echo(f"Linked {source_type}:{source[:12]} --{relation}--> {target_type}:{target[:12]}")


@main.command()
@click.argument("entity_id")
@click.option("--type", "entity_type", default="journey")
@click.option("--depth", default=5)
def trace(entity_id, entity_type, depth):
    """Walk the relationship graph from an entity."""
    container = create_container()
    rels = container.relationship_repo.trace(entity_type, entity_id, max_depth=depth)
    container.close()

    if not rels:
        click.echo("No relationships found.")
        return

    click.echo(f"\nRelationship graph ({len(rels)} edges):")
    for r in rels:
        src = f"{r['source_type']}:{r['source_id'][:12]}"
        tgt = f"{r['target_type']}:{r['target_id'][:12]}"
        click.echo(f"  {src} --{r['relation']}--> {tgt}")


# ── Migration commands ─────────────────────────────────────────────────────


@main.group()
def migrate():
    """Migration tools."""
    pass


@migrate.command("echovault")
@click.option("--source", default=None, help="Source EchoVault home (default: ~/.memory)")
def migrate_echovault(source):
    """Migrate from EchoVault."""
    from arcane.services.migration import MigrationService

    svc = MigrationService()
    result = svc.migrate_from_echovault(source_home=source)

    if result["success"]:
        click.echo(f"Migration complete: {result['memory_count']} memories")
        click.echo(f"  From: {result['source']}")
        click.echo(f"  To:   {result['target']}")
        for err in result.get("errors", []):
            click.echo(f"  Note: {err}")
    else:
        for err in result.get("errors", []):
            click.echo(f"Error: {err}")


@migrate.command("check")
def migrate_check():
    """Verify migration integrity."""
    from arcane.services.migration import MigrationService

    svc = MigrationService()
    result = svc.verify()

    if result.get("success"):
        click.echo("Migration verification:")
        click.echo(f"  Memories:      {result.get('memories_count', 0)}")
        click.echo(f"  Journeys:      {result.get('journeys_count', 0)}")
        click.echo(f"  Artifacts:     {result.get('artifacts_count', 0)}")
        click.echo(f"  Relationships: {result.get('relationships_count', 0)}")
        click.echo(f"  Insights:      {result.get('insights_count', 0)}")
        click.echo(f"  FTS synced:    {result.get('fts_synced', False)}")
        click.echo(f"  Vec table:     {result.get('vec_table_exists', False)}")
        click.echo(f"  Embedding dim: {result.get('embedding_dim', 'N/A')}")
    else:
        for err in result.get("errors", []):
            click.echo(f"Error: {err}")


# ── Config commands ────────────────────────────────────────────────────────


@main.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """Show or manage configuration."""
    if ctx.invoked_subcommand is None:
        home, source = resolve_home()
        cfg = load_config(os.path.join(home, "config.yaml"))
        data = _redact_api_keys(asdict(cfg))
        data["arcane_home"] = home
        data["arcane_home_source"] = source
        click.echo(yaml.safe_dump(data, sort_keys=False))


@config.command("set-home")
@click.argument("path")
def config_set_home(path):
    """Persist arcane home location."""
    resolved = set_persisted_home(path)
    os.makedirs(resolved, exist_ok=True)
    os.makedirs(os.path.join(resolved, "vault"), exist_ok=True)
    click.echo(f"Persisted arcane home: {resolved}")


@config.command("clear-home")
def config_clear_home():
    """Remove persisted home setting."""
    changed = clear_persisted_home()
    click.echo("Cleared." if changed else "No setting found.")


# ── Stats command ──────────────────────────────────────────────────────────


@main.command()
def stats():
    """Show database statistics."""
    container = create_container()
    click.echo("Arcane statistics:")
    click.echo(f"  Memories:      {container.memory_repo.count()}")
    click.echo(f"  Journeys:      {container.journey_repo.count()}")
    click.echo(f"  Artifacts:     {container.artifact_repo.count()}")
    click.echo(f"  Relationships: {container.relationship_repo.count()}")
    click.echo(f"  Insights:      {container.insight_repo.count()}")
    click.echo(f"  Home:          {container.home}")
    container.close()


# ── Ingestion commands ─────────────────────────────────────────────────────


@main.group()
def ingest():
    """Ingest data from external sources."""
    pass


@ingest.command("git")
@click.option("--project", default=None, help="Project name")
@click.option("--repo-path", default=None, help="Path to git repo (default: cwd)")
@click.option("--max-count", default=100, help="Max commits to ingest")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_git(project, repo_path, max_count, journey_id):
    """Ingest commits from a git repository."""
    from arcane.plugins.builtin.git_ingest import GitIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = GitIngestionPlugin(repo_path=repo_path or os.getcwd(), max_count=max_count)

    container = create_container()
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    container.close()

    click.echo(f"Git ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("gha")
@click.option("--owner", required=True, help="GitHub repo owner")
@click.option("--repo", required=True, help="GitHub repo name")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_gha(owner, repo, project, journey_id):
    """Ingest CI runs from GitHub Actions."""
    from arcane.plugins.builtin.gha_ingest import GHAIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = GHAIngestionPlugin(owner=owner, repo=repo)

    container = create_container()
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    container.close()

    click.echo(f"GHA ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


@ingest.command("linear")
@click.option("--team", required=True, help="Linear team ID")
@click.option("--project", default=None, help="Project name")
@click.option("--journey-id", default=None, help="Link artifacts to a journey")
def ingest_linear(team, project, journey_id):
    """Ingest tickets from Linear."""
    from arcane.plugins.builtin.linear_ingest import LinearIngestionPlugin
    from arcane.services.ingestion import IngestionService

    project = project or os.path.basename(os.getcwd())
    plugin = LinearIngestionPlugin(team_id=team)

    container = create_container()
    svc = IngestionService(container)
    result = svc.run_plugin(plugin, project=project, journey_id=journey_id)
    container.close()

    click.echo(f"Linear ingestion: {result['ingested']} ingested, {result['skipped']} skipped")


# ── Analysis commands ─────────────────────────────────────────────────────


@main.group()
def analyze():
    """Run intelligence analysis plugins."""
    pass


@analyze.command("flakes")
@click.option("--project", default=None, help="Project name")
def analyze_flakes(project):
    """Detect flaky CI runs."""
    from arcane.plugins.builtin.ci_flakes import CIFlakeDetector
    from arcane.services.intelligence import IntelligenceService

    project = project or os.path.basename(os.getcwd())
    container = create_container()
    plugin = CIFlakeDetector(artifact_repo=container.artifact_repo)

    svc = IntelligenceService(container)
    result = svc.run_plugin(plugin, project=project)
    container.close()

    if result["insights_created"] > 0:
        click.echo(f"CI flake analysis: {result['insights_created']} insight(s) created")
    else:
        click.echo("No CI flakes detected.")


@analyze.command("velocity")
@click.option("--project", default=None, help="Project name")
def analyze_velocity(project):
    """Generate engineering velocity summary."""
    from arcane.plugins.builtin.velocity import VelocityTracker
    from arcane.services.intelligence import IntelligenceService

    project = project or os.path.basename(os.getcwd())
    container = create_container()
    plugin = VelocityTracker(
        artifact_repo=container.artifact_repo,
        memory_repo=container.memory_repo,
        journey_repo=container.journey_repo,
    )

    svc = IntelligenceService(container)
    result = svc.run_plugin(plugin, project=project)
    container.close()

    click.echo(f"Velocity analysis: {result['insights_created']} insight(s) created")


# ── Content generation commands ───────────────────────────────────────────


@main.group()
def draft():
    """Generate structured content briefs."""
    pass


@draft.command("blog")
@click.option("--journey-id", default=None, help="Journey to generate brief from")
@click.option("--project", default=None, help="Project for memory-based brief")
def draft_blog(journey_id, project):
    """Generate a structured blog brief."""
    from arcane.plugins.builtin.blog_gen import BlogGenerator

    container = create_container()

    context: dict = {}
    if journey_id:
        from arcane.services.journey import JourneyService
        js = JourneyService(container)
        journey_data = js.show(journey_id)
        if not journey_data:
            click.echo(f"Journey {journey_id} not found.")
            container.close()
            return
        context["journey"] = journey_data
    elif project:
        memories = container.memory_repo.list_recent(limit=20, project=project)
        context["memories"] = memories
        context["project"] = project
    else:
        click.echo("Provide --journey-id or --project.")
        container.close()
        return

    gen = BlogGenerator()
    brief = gen.generate(context)
    container.close()

    click.echo(brief)


@draft.command("adr")
@click.argument("memory_id")
def draft_adr(memory_id):
    """Generate a structured ADR from a decision memory."""
    from arcane.plugins.builtin.adr_gen import ADRGenerator

    container = create_container()
    mem = container.memory_repo.get(memory_id)
    if not mem:
        click.echo(f"Memory {memory_id} not found.")
        container.close()
        return

    detail = container.memory_repo.get_details(memory_id)
    detail_body = detail["body"] if detail else ""

    gen = ADRGenerator()
    adr = gen.generate(context={"memory": mem, "details": detail_body})
    container.close()

    click.echo(adr)


# ── MCP server command ─────────────────────────────────────────────────────


@main.command()
def mcp():
    """Start the Arcane MCP server (stdio transport)."""
    import asyncio

    from arcane.mcp_server.server import run_server

    asyncio.run(run_server())


# ── Sessions command ───────────────────────────────────────────────────────


@main.command()
@click.option("--limit", default=10)
@click.option("--project", default=None)
def sessions(limit, project):
    """List recent sessions."""
    container = create_container()
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

    container.close()

    if not session_files:
        click.echo("No sessions found.")
        return

    click.echo("\nSessions:")
    for proj, fname in session_files[:limit]:
        date_str = fname.replace("-session.md", "")
        click.echo(f"  {date_str} | {proj}")


if __name__ == "__main__":
    main()
