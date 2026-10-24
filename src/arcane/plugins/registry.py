"""Plugin discovery via Python entry points."""

from __future__ import annotations

import inspect
import logging
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from arcane.domain.scope import resolve_write_scope

if TYPE_CHECKING:
    from arcane.services.container import ServiceContainer

logger = logging.getLogger(__name__)

PLUGIN_KINDS = ("ingestion", "intelligence", "content")

# Built-in CLI commands named differently from the entry point they run.
COMMAND_ALIASES: dict[str, dict[str, str]] = {"ingestion": {"gha": "github_actions"}}


def command_name(kind: str, entry_point: str) -> str:
    """The CLI command that runs *entry_point*: its alias, or its own name."""
    aliases = {target: alias for alias, target in COMMAND_ALIASES.get(kind, {}).items()}
    return aliases.get(entry_point, entry_point)


class PluginError(ValueError):
    """An installed plugin could not be selected or configured."""


def plugins_for(kind: str) -> dict[str, Any]:
    """Return installed plugin factories keyed by their entry-point names."""
    if kind not in PLUGIN_KINDS:
        raise PluginError(f"Unknown plugin kind: {kind}. Choose {', '.join(PLUGIN_KINDS)}.")
    return discover_plugins(f"arcane.plugins.{kind}")


def describe_plugins(kind: str) -> list[dict[str, str]]:
    """Describe constructor options without constructing plugins or opening stores."""
    return [
        {"name": name, "description": inspect.getdoc(factory) or "", "options": str(inspect.signature(factory))}
        for name, factory in sorted(plugins_for(kind).items())
    ]


def create_plugin(
    kind: str,
    name: str,
    container: ServiceContainer,
    options: dict[str, Any] | None = None,
) -> Any:
    """Construct an entry-point plugin with requested options and accepted dependencies.

    Factories may accept the same named repository dependencies as built-ins.
    Only explicitly declared parameters receive dependencies; arbitrary **kwargs
    never gives a plugin accidental access to every repository.
    """
    name = COMMAND_ALIASES.get(kind, {}).get(name, name)
    factories = plugins_for(kind)
    if name not in factories:
        raise PluginError(f"Unknown {kind} plugin: {name}. Available: {', '.join(sorted(factories)) or '(none)'}.")
    factory = factories[name]
    supplied = options or {}
    repo_path = supplied.get("repo_path") if kind == "ingestion" else None
    dependencies = {
        "memory_repo": container.memory_repo,
        "artifact_repo": container.artifact_repo,
        "journey_repo": container.journey_repo,
        "retrieval_repo": container.retrieval_repo,
        "aliases": container.config.projects.aliases,
        "org": resolve_write_scope(None, container.config, repo_path=repo_path).org,
    }
    try:
        signature = inspect.signature(factory)
        kwargs = {key: value for key, value in dependencies.items() if key in signature.parameters}
        if supplied.keys() & dependencies.keys():
            raise PluginError("Injected dependencies and org cannot be overridden with plugin options.")
        kwargs.update(supplied)
        signature.bind(**kwargs)
        plugin = factory(**kwargs)
    except (TypeError, ValueError) as exc:
        raise PluginError(f"Cannot configure {kind} plugin '{name}': {exc}") from exc
    method = {"ingestion": "ingest", "intelligence": "analyze", "content": "generate"}[kind]
    if not isinstance(getattr(plugin, "name", None), str) or not callable(getattr(plugin, method, None)):
        raise PluginError(f"Plugin '{name}' must provide a name and {method}() method.")
    return plugin


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
