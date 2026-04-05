"""Configuration loading and management."""

from __future__ import annotations

import os
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

APP_NAME = "arcane"
LEGACY_APP_NAME = "echovault"


class EmbeddingConfig(BaseModel):
    """Embedding provider configuration."""

    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str | None = "http://localhost:11434"
    api_key: str | None = None

    model_config = {"extra": "ignore"}


class ContextConfig(BaseModel):
    """Context retrieval configuration."""

    semantic: Literal["auto", "always", "never"] = "auto"
    topup_recent: bool = True

    model_config = {"extra": "ignore"}


class ArcaneConfig(BaseModel):
    """Top-level Arcane configuration."""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)

    model_config = {"extra": "ignore"}


def _global_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", APP_NAME, "config.yaml")


def _legacy_global_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", LEGACY_APP_NAME, "config.yaml")


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def get_persisted_home() -> str | None:
    """Return persisted home from global config, if set."""
    for path in [_global_config_path(), _legacy_global_config_path()]:
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            continue

        for key in ["arcane_home", "memory_home"]:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_path(value.strip())

    return None


def set_persisted_home(path: str) -> str:
    """Persist arcane home in global config and return normalized value."""
    normalized = _normalize_path(path)
    cfg_path = _global_config_path()
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)

    data: dict[str, Any] = {}
    try:
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pass

    data["arcane_home"] = normalized
    with open(cfg_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    return normalized


def clear_persisted_home() -> bool:
    """Clear persisted home from global config; return True if changed."""
    cfg_path = _global_config_path()
    try:
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return False

    if "arcane_home" not in data:
        return False

    del data["arcane_home"]
    if data:
        with open(cfg_path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
    else:
        os.remove(cfg_path)
    return True


def resolve_home() -> tuple[str, str]:
    """Resolve arcane home and return (path, source)."""
    # 1. ARCANE_HOME env var
    env_home = os.environ.get("ARCANE_HOME")
    if env_home:
        return _normalize_path(env_home), "env"

    # 2. Legacy MEMORY_HOME env var (backward compat)
    env_home = os.environ.get("MEMORY_HOME")
    if env_home:
        return _normalize_path(env_home), "env"

    # 3. Persisted config
    persisted = get_persisted_home()
    if persisted:
        return persisted, "config"

    # 4. Default
    return os.path.join(os.path.expanduser("~"), ".arcane"), "default"


def get_home() -> str:
    return resolve_home()[0]


def load_config(path: str) -> ArcaneConfig:
    """Load ``ArcaneConfig`` from a YAML file, falling back to defaults."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return ArcaneConfig()

    return ArcaneConfig.model_validate(data)
