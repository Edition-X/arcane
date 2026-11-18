"""Revisit block shared by ``arcane context``: memories whose ``revisit_when`` date has come."""

from __future__ import annotations

from typing import Any

import click


def echo_revisit(due: list[dict[str, Any]]) -> None:
    """Print the memories due for a second look, oldest date first; nothing when none are due."""
    if not due:
        return
    click.echo(f"Due for a second look ({len(due)}):")
    for r in due:
        project_part = f" ({r['project']})" if r.get("project") else ""
        cat_part = f" [{r['category']}]" if r.get("category") else ""
        click.echo(f"- [{r['revisit_when']}] {r['title']}{project_part}{cat_part} (id: {r['id'][:12]})")
