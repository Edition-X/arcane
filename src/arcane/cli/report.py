"""Report and export commands — what was done in a period, and one org's data."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import click

from arcane.cli._utils import create_container


def _parse_date(value: str | None, param: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise click.BadParameter("use YYYY-MM-DD", param_hint=param) from exc


@click.command()
@click.option("--since", default=None, help="First day, YYYY-MM-DD (default: --days before --until).")
@click.option("--until", default=None, help="Last day, YYYY-MM-DD, included (default: today).")
@click.option("--days", default=7, show_default=True, help="Period length when --since is not given.")
@click.option("--org", default=None, help="Only this org, e.g. sunrise-robotics.")
@click.option("--project", default=None, help="Only this project.")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown", show_default=True)
def report(since: str | None, until: str | None, days: int, org: str | None, project: str | None, fmt: str) -> None:
    """What was shipped, decided, fixed and finished in a period, by org and project."""
    from arcane.domain.scope import canonicalize_project, slugify
    from arcane.services.report import build_report, render_markdown

    end = _parse_date(until, "--until") or date.today()
    start = _parse_date(since, "--since") or end - timedelta(days=max(days, 1) - 1)
    if start > end:
        raise click.BadParameter("must not be after --until", param_hint="--since")

    with create_container() as container:
        aliases = container.config.projects.aliases
        result = build_report(
            container,
            start,
            end,
            org=slugify(org) if org else None,
            project=canonicalize_project(project, aliases) if project else None,
        )

    click.echo(json.dumps(result, indent=2) if fmt == "json" else render_markdown(result), nl=fmt == "json")


@click.command(name="export")
@click.option("--org", required=True, help="Org to export, e.g. sunrise-robotics.")
@click.option("--out", default=None, help="Output file (default: arcane-export-<org>-<date>.json here).")
def export(org: str, out: str | None) -> None:
    """Export one org's memories, journeys, artifacts and links as JSON."""
    from arcane.domain.scope import slugify
    from arcane.services.report import export_org

    org_slug = slugify(org)
    path = out or f"arcane-export-{org_slug}-{date.today().isoformat()}.json"
    with create_container() as container:
        data = export_org(container, org_slug)
    if not data["memories"]:
        raise click.ClickException(f"No memories in org '{org_slug}'. `arcane projects` lists orgs.")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    counts = data["counts"]
    click.echo(
        f"Exported {counts['memories']} memories, {counts['journeys']} journeys, {counts['artifacts']} artifacts "
        f"and {counts['relationships']} links from {len(data['projects'])} projects to {os.path.abspath(path)}"
    )
