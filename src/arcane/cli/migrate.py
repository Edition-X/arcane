"""Migration commands — echovault and check."""

from __future__ import annotations

import click


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
