"""Generic installed-plugin discovery and execution without per-plugin tools."""

from __future__ import annotations

import json
from typing import Any

from arcane.domain.scope import resolve_write_scope
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.infra.redaction import redact
from arcane.plugins.protocols import IngestionError
from arcane.plugins.registry import PLUGIN_KINDS, PluginError, create_plugin, describe_plugins
from arcane.services.container import ServiceContainer
from arcane.services.ingestion import IngestionService
from arcane.services.intelligence import IntelligenceService


def handle_plugins(
    container: ServiceContainer,
    kind: str | None = None,
    plugin_name: str | None = None,
    options: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    project: str | None = None,
    journey_id: str | None = None,
) -> str:
    """List installed plugins, or execute one by kind and entry-point name."""
    try:
        if plugin_name is None:
            return json.dumps({k: describe_plugins(k) for k in ([kind] if kind else PLUGIN_KINDS)})
        if kind is None:
            raise PluginError("Provide kind to run a plugin: ingestion, intelligence, or content.")
        plugin = create_plugin(kind, plugin_name, container, options)
        if kind == "ingestion":
            result = IngestionService(container).run_plugin(
                plugin, project=project, journey_id=journey_id, repo_path=(options or {}).get("repo_path")
            )
        elif kind == "intelligence":
            result = IntelligenceService(container).run_plugin(plugin, project=project)
        else:
            content_context = dict(context or {})
            content_context["org"] = resolve_write_scope(project, container.config).org
            if project is not None:
                content_context["project"] = project
            result = {
                "plugin": plugin.name,
                "brief": redact(plugin.generate(content_context), container.ignore_patterns),
            }
        return json.dumps(result)
    except (PluginError, IngestionError, IdentifierResolutionError) as exc:
        return json.dumps({"error": str(exc)})
