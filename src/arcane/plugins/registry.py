"""Plugin discovery via Python entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any


def discover_plugins(group: str) -> dict[str, Any]:
    """Discover all installed plugins for a given group.

    Groups:
        arcane.plugins.ingestion
        arcane.plugins.intelligence
        arcane.plugins.content
    """
    eps = entry_points(group=group)
    plugins: dict[str, Any] = {}
    for ep in eps:
        try:
            plugins[ep.name] = ep.load()
        except Exception:
            pass
    return plugins
