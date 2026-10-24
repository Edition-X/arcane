"""Backup command — snapshot the database and vault into a rotated archive."""

from __future__ import annotations

import os

import click


@click.command()
@click.option(
    "--dest",
    default=None,
    help="Directory for archives (default: <home>/backups). Point it off this disk to survive a disk loss.",
)
@click.option("--keep", default=14, show_default=True, help="Archives to keep; older ones are deleted. 0 keeps all.")
def backup(dest: str | None, keep: int) -> None:
    """Back up the database and vault to a timestamped .tar.gz."""
    from arcane.infra.config import get_home
    from arcane.services.backup import BackupError, create_backup

    if keep < 0:
        raise click.BadParameter("must be 0 or more", param_hint="--keep")
    home = get_home()
    target = os.path.expanduser(dest) if dest else os.path.join(home, "backups")
    try:
        result = create_backup(home, target, keep=keep)
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Backed up {result.memories} memories to {result.path} ({result.size_bytes / 1_000_000:.1f} MB)")
    for name in result.pruned:
        click.echo(f"  removed old backup {name}")
