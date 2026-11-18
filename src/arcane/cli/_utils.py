"""Shared utilities for CLI command modules.

Centralises the ``create_container`` import so tests have a single patch
target: ``arcane.cli._utils.create_container``.
"""

from __future__ import annotations

from datetime import date, datetime

import click

from arcane.services.container import ServiceContainer, create_container

__all__ = ["ServiceContainer", "create_container", "parse_date"]


def parse_date(value: str | None, param: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` option value; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise click.BadParameter("use YYYY-MM-DD", param_hint=param) from exc
