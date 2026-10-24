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


@migrate.command("entity-org")
@click.option("--org", required=True, help="Verified owner of the unknown legacy entities.")
@click.option("--project", required=True, help="Exact stored project name to recover.")
@click.option("--apply", "apply_", is_flag=True, default=False, help="Assign ownership (default: dry run).")
def migrate_entity_org(org: str, project: str, apply_: bool) -> None:
    """Assign explicitly verified ownership to unknown journeys, artifacts and insights.

    Shared project names cannot establish historical ownership. Inspect the
    records and their sources before using this command; it assigns every
    unknown entity in the selected project, and never changes a known org.
    """
    from arcane.domain.scope import validate_org

    try:
        org = validate_org(org)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--org") from exc
    if not project:
        raise click.BadParameter("must be a nonempty stored project name", param_hint="--project")

    tables = ("journeys", "artifacts", "insights")
    with create_container() as container:

        def plan() -> dict[str, int]:
            # A duplicate external key cannot be reassigned without either
            # overwriting a known record or silently discarding the unknown one.
            conflicts = container.db.fetchall(
                "SELECT unknown.id, known.id AS existing_id FROM artifacts unknown JOIN artifacts known "
                "ON known.artifact_type = unknown.artifact_type AND known.external_id = unknown.external_id "
                "AND known.project = unknown.project AND known.org = ? "
                "WHERE unknown.project = ? AND unknown.org = ''",
                (org, project),
            )
            if conflicts:
                ids = ", ".join(f"{r['id']} conflicts with {r['existing_id']}" for r in conflicts[:5])
                raise click.ClickException(
                    f"Ownership conflict: {ids}. Resolve duplicate artifacts before assigning ownership; "
                    "nothing changed."
                )
            counts = {}
            for table in tables:
                row = container.db.fetchone(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE project = ? AND org = ''", (project,)
                )
                counts[table] = row["n"] if row else 0
            return counts

        counts = plan()
        if not sum(counts.values()):
            click.echo(f"No unknown-org entities in project '{project}'. Known ownership is unchanged.")
            return
        click.echo(f"{'Assign' if apply_ else 'Dry run'}: unknown entities in '{project}' -> {org}/{project}")
        for table, count in counts.items():
            click.echo(f"  {table}: {count}")
            for row in container.db.fetchall(
                f"SELECT id, title FROM {table} WHERE project = ? AND org = '' ORDER BY id LIMIT 20", (project,)
            ):
                click.echo(f"    {row['id']}  {row['title']}")
            if count > 20:
                click.echo(f"    ... {count - 20} more records")
        click.echo("Known orgs and memories are unchanged. Verify these records belong to this org before applying.")
        if not apply_:
            click.echo("Pass --apply to back up the SQLite store and assign ownership atomically.")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup = f"{container.db.db_path}.bak-entity-org-{timestamp}"
        container.db.backup(backup)
        with container.db.transaction():
            # Check again under the write lock, so a concurrent ingestion cannot
            # create a conflict between the dry run and the update.
            plan()
            updated = 0
            for table in tables:
                cursor = container.db.execute(
                    f"UPDATE {table} SET org = ? WHERE project = ? AND org = ''", (org, project)
                )
                updated += cursor.rowcount
    click.echo(f"Assigned {updated} entities to {org}/{project}.")
    click.echo(f"Backup: {backup}")
