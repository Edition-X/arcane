"""IntelligenceService — orchestrates analysis plugins and insight storage."""

from __future__ import annotations

from typing import Any

from arcane.domain.scope import resolve_write_scope
from arcane.infra.redaction import redact_values
from arcane.plugins.protocols import IntelligencePlugin
from arcane.services.container import ServiceContainer


class IntelligenceService:
    """Runs intelligence plugins and stores their output as insights."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def run_plugin(
        self,
        plugin: IntelligencePlugin,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Run a single intelligence plugin and store results."""
        project = resolve_write_scope(project, self.c.config).project
        insights = plugin.analyze(project=project)

        for insight in insights:
            insight.update(redact_values(insight, self.c.ignore_patterns))
            insight["project"] = project
            self.c.insight_repo.insert(insight)

        return {
            "plugin": plugin.name,
            "project": project,
            "insights_created": len(insights),
        }

    def run_all(
        self,
        plugins: list[IntelligencePlugin],
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run multiple intelligence plugins."""
        return [self.run_plugin(plugin, project=project) for plugin in plugins]
