"""Config commands — show, set-home, clear-home."""

from __future__ import annotations

import os

import click
import yaml

from arcane.infra.config import (
    clear_persisted_home,
    load_config,
    resolve_home,
    set_persisted_home,
)


def _redact_api_keys(data: dict) -> dict:
    for section in ("embedding",):
        cfg = data.get(section)
        if isinstance(cfg, dict) and cfg.get("api_key"):
            cfg["api_key"] = "<redacted>"
    return data


@click.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show or manage configuration."""
    if ctx.invoked_subcommand is None:
        home, source = resolve_home()
        cfg = load_config(os.path.join(home, "config.yaml"))
        data = _redact_api_keys(cfg.model_dump())
        data["arcane_home"] = home
        data["arcane_home_source"] = source
        click.echo(yaml.safe_dump(data, sort_keys=False))


@config.command("set-home")
@click.argument("path")
def config_set_home(path: str) -> None:
    """Persist arcane home location."""
    resolved = set_persisted_home(path)
    os.makedirs(resolved, exist_ok=True)
    os.makedirs(os.path.join(resolved, "vault"), exist_ok=True)
    click.echo(f"Persisted arcane home: {resolved}")


@config.command("clear-home")
def config_clear_home() -> None:
    """Remove persisted home setting."""
    changed = clear_persisted_home()
    click.echo("Cleared." if changed else "No setting found.")
