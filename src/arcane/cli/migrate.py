"""Migration commands — echovault and check."""

from __future__ import annotations

from datetime import datetime, timezone

import click

from arcane.cli._utils import create_container


@click.group()
def migrate() -> None:
    """Migration tools."""


@migrate.command("echovault")
@click.option("--source", default=None, help="Source EchoVault home (default: ~/.memory)")
def migrate_echovault(source: str | None) -> None:
    """Migrate from EchoVault."""
    from arcane.services.migration import MigrationService

    result = MigrationService().migrate_from_echovault(source_home=source)

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
def migrate_check() -> None:
    """Verify migration integrity."""
    from arcane.services.migration import MigrationService

    result = MigrationService().verify()

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


@migrate.command("org-scope")
@click.option("--apply", "apply_", is_flag=True, default=False, help="Write the backfill (default: dry run).")
def migrate_org_scope(apply_: bool) -> None:
    """Backfill empty memory orgs and canonical project names."""
    from arcane.services.migration import MigrationService

    with create_container() as container:
        service = MigrationService()
        plan = service.backfill_org(
            container.db,
            remotes=container.config.orgs.remotes,
            overrides=container.config.orgs.overrides,
            aliases=container.config.projects.aliases,
            default=container.config.orgs.default,
            dry_run=True,
        )
        if not plan["planned"]:
            click.echo("No empty-org memories found.")
            return

        if not apply_:
            click.echo(f"Dry run: {sum(item['count'] for item in plan['planned'])} memories would be backfilled.")
            for item in plan["planned"]:
                click.echo(
                    f"  {item['count']:5d}  {item['old_project'] or '<no project>'} "
                    f"-> {item['new_org']}/{item['new_project']}"
                )
            click.echo("Pass --apply to write a SQLite-backed, transactional migration.")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = f"{container.db.db_path}.bak-orgscope-{timestamp}"
        container.db.backup(backup)
        result = service.backfill_org(
            container.db,
            remotes=container.config.orgs.remotes,
            overrides=container.config.orgs.overrides,
            aliases=container.config.projects.aliases,
            default=container.config.orgs.default,
            dry_run=False,
        )

    click.echo(f"Backfilled {result['updated']} memories.")
    click.echo(f"Backup: {backup}")
