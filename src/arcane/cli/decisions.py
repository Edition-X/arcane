"""Decision log command — a project's current decisions as a document."""

from __future__ import annotations

import json
import os

import click

from arcane.cli._utils import create_container


@click.command()
@click.option("--project", default=None, help="Project (default: the current git remote's).")
@click.option("--org", default=None, help="Org. Alone, it logs every project of the org.")
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default="md", show_default=True)
@click.option("--out", default=None, help="Write to this file instead of printing.")
def decisions(project: str | None, org: str | None, fmt: str, out: str | None) -> None:
    """Print the decision log: current decisions newest first, then the ones replaced."""
    from arcane.domain.scope import resolve_read_project, resolve_scope, slugify
    from arcane.infra.redaction import redact
    from arcane.services.decisions import build_decision_log, render_markdown

    with create_container() as container:
        here = resolve_scope(os.getcwd(), container.config)
        if org and not project:
            scope_org, scope_project = slugify(org), None
        else:
            scope_org = slugify(org) if org else here.org
            scope_project = resolve_read_project(project, container.config) if project else here.project
        log = build_decision_log(container, org=scope_org, project=scope_project)
        text = json.dumps(log, indent=2) + "\n" if fmt == "json" else render_markdown(log)
        text = redact(text, container.ignore_patterns)

    if out is None:
        click.echo(text, nl=False)
        return
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    click.echo(f"Wrote {len(log['decisions'])} decisions and {len(log['replaced'])} replaced to {os.path.abspath(out)}")
