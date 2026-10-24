"""Shared Click surface for installed entry-point plugins."""

from __future__ import annotations

import json
from typing import Any

import click

from arcane.cli._utils import create_container
from arcane.domain.scope import resolve_write_scope
from arcane.infra.db.ids import IdentifierResolutionError
from arcane.infra.redaction import redact
from arcane.plugins.protocols import IngestionError
from arcane.plugins.registry import PluginError, create_plugin, describe_plugins, plugins_for


def json_object(value: str) -> dict[str, Any]:
    """Parse a JSON object passed at the command boundary."""
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise click.BadParameter(f"Expected a JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter("Expected a JSON object")
    return parsed


def list_plugins(kind: str) -> None:
    for plugin in describe_plugins(kind):
        description = plugin["description"].splitlines()[0] if plugin["description"] else "(no description)"
        click.echo(f"{plugin['name']}: {description}")


class PluginGroup(click.Group):
    """Keep existing commands and discover additional installed plugins lazily."""

    def __init__(self, *args: Any, kind: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.kind = kind

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except (PluginError, IngestionError, IdentifierResolutionError) as exc:
            raise click.ClickException(str(exc)) from exc

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(set(super().list_commands(ctx)) | set(plugins_for(self.kind)))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        existing = super().get_command(ctx, cmd_name)
        if existing:
            return existing
        descriptions = {p["name"]: p for p in describe_plugins(self.kind)}
        if cmd_name not in descriptions:
            return None
        info = descriptions[cmd_name]

        @click.command(cmd_name, help=f"{info['description']}\n\nConstructor options: {info['options']}")
        @click.option("--options", default="{}", help="Plugin constructor options as a JSON object.")
        @click.option("--project", default=None, help="Project name (default: current repository).")
        @click.option("--journey-id", default=None, help="Link ingested artifacts to a journey.")
        @click.option("--context", default="{}", help="Content generation context as a JSON object.")
        def run(options: str, project: str | None, journey_id: str | None, context: str) -> None:
            settings = json_object(options)
            content_context = json_object(context)
            try:
                with create_container() as container:
                    plugin = create_plugin(self.kind, cmd_name, container, settings)
                    if self.kind == "ingestion":
                        from arcane.services.ingestion import IngestionService

                        result = IngestionService(container).run_plugin(
                            plugin, project=project, journey_id=journey_id, repo_path=settings.get("repo_path")
                        )
                    elif self.kind == "intelligence":
                        from arcane.services.intelligence import IntelligenceService

                        result = IntelligenceService(container).run_plugin(plugin, project=project)
                    else:
                        content_context["org"] = resolve_write_scope(project, container.config).org
                        if project is not None:
                            content_context["project"] = project
                        click.echo(redact(plugin.generate(content_context), container.ignore_patterns))
                        return
            except (PluginError, IngestionError, IdentifierResolutionError) as exc:
                raise click.ClickException(str(exc)) from exc
            click.echo(json.dumps(result))

        return run
