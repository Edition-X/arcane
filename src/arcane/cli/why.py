"""Why command — the decisions behind a file or a commit."""

from __future__ import annotations

import json
from typing import Any

import click

from arcane.cli._utils import create_container


def _print_entry(entry: dict[str, Any]) -> None:
    meta = (entry["id"][:8], entry["date"], entry["project"], entry["category"])
    click.echo(f"\n[{' | '.join(part for part in meta if part)}] {entry['title']}")
    click.echo(f"  What: {entry['what']}")
    if entry["why"]:
        click.echo(f"  Why: {entry['why']}")
    if entry["via"] == "commit":
        click.echo("  Saved at this commit")
    replaced = entry.get("superseded_by")
    if replaced:
        click.echo(f"  Replaced by {replaced['id'][:8]}: {replaced['title']}")


@click.command()
@click.argument("target")
@click.option("--all", "everywhere", is_flag=True, help="Read every project, not only the current one.")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON, for agents.")
def why(target: str, everywhere: bool, as_json: bool) -> None:
    """Show the decisions and bugs behind a file path or a commit (7+ hex characters).

    A file lists the decisions and bugs whose related files name it, newest first,
    then the ones a newer memory replaced. A commit lists the memories saved at it,
    then the decisions on the files it touched.
    """
    from arcane.services.why import WhyError, WhyService

    with create_container() as container:
        try:
            result = WhyService(container).why(target, everywhere=everywhere)
        except WhyError as exc:
            raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(result.as_dict(), indent=2))
        return
    subject = f"commit {result.commit[:12]}" if result.commit else result.files[0]
    click.echo(f"{subject}: {len(result.memories)} current, {len(result.superseded)} replaced")
    if not result.memories and not result.superseded:
        click.echo("No decisions or bugs found." + ("" if everywhere else " Try --all to read every project."))
    for entry in result.memories:
        _print_entry(entry)
    if result.superseded:
        click.echo("\nReplaced:")
        for entry in result.superseded:
            _print_entry(entry)
