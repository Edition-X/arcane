"""``arcane coverage`` — merged PRs and commits with no memory behind them."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import click

from arcane.cli._utils import create_container, parse_date


@click.command()
@click.option("--since", default=None, help="First day, YYYY-MM-DD (default: --days ago).")
@click.option("--days", default=30, show_default=True, help="Days back, today included, when --since is not given.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print every item and the rule that matched it.")
def coverage(since: str | None, days: int, as_json: bool) -> None:
    """Which merged PRs and commits of this repo have no linked memory.

    Walks the default branch's first-parent history and checks each PR and direct
    commit against this project's memories: by commit SHA, PR head branch, a pr-N tag,
    or "PR N" / "#N" in the text. Exit status is 0 whatever the result.
    """
    from arcane.services.coverage import build_coverage, render_text

    start = parse_date(since, "--since") or date.today() - timedelta(days=max(days, 1) - 1)
    with create_container() as container:
        result = build_coverage(container, os.getcwd(), start)
    click.echo(json.dumps(result, indent=2) if as_json else render_text(result))
