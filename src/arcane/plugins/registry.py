"""Plugin discovery via Python entry points."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

logger = logging.getLogger(__name__)


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
            logger.warning("Failed to load plugin '%s' from group '%s'", ep.name, group, exc_info=True)
    return plugins
