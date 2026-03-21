"""IntelligenceService — orchestrates analysis plugins and insight storage."""

from __future__ import annotations

from typing import Any

from arcane.plugins.protocols import IntelligencePlugin
from arcane.services.container import ServiceContainer


class IntelligenceService:
    """Runs intelligence plugins and stores their output as insights."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def run_plugin(
        self,
        plugin: IntelligencePlugin,
        project: str,
    ) -> dict[str, Any]:
        """Run a single intelligence plugin and store results."""
        insights = plugin.analyze(project=project)

        for insight in insights:
            self.c.insight_repo.insert(insight)

        return {
            "plugin": plugin.name,
            "insights_created": len(insights),
        }

    def run_all(
        self,
        plugins: list[IntelligencePlugin],
        project: str,
    ) -> list[dict[str, Any]]:
        """Run multiple intelligence plugins."""
        return [self.run_plugin(plugin, project=project) for plugin in plugins]
