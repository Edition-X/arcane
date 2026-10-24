"""Configuration loading and management."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

APP_NAME = "arcane"
LEGACY_APP_NAME = "echovault"

# An org names a vault directory and partitions every scoped read, so only
# canonical slugs are accepted. Defined here, the lowest layer that needs it,
# because ``arcane.domain.scope`` already imports this module — it re-exports
# this rule as ``validate_org`` rather than keeping a second copy of the regex.
_ORG_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ConfigError(ValueError):
    """``config.yaml`` could not be read or does not describe a valid configuration."""


def validate_org_slug(value: str) -> str:
    """Accept only canonical org slugs, so an org can safely name a directory."""
    value = value.strip().lower()
    if not _ORG_SLUG.fullmatch(value):
        raise ValueError("Org must be a nonempty slug containing letters, digits and single hyphens")
    return value


class EmbeddingConfig(BaseModel):
    """Embedding provider configuration."""

    provider: Literal["ollama", "openai", "none"] = "ollama"
    model: str = "nomic-embed-text"
    base_url: str | None = "http://localhost:11434"
    api_key: str | None = None
    # Start a local Ollama when it is not running (provider "ollama" only).
    # The ARCANE_OLLAMA_AUTOSTART=0 env var overrides this to off.
    autostart: bool = True

    model_config = {"extra": "ignore"}


class ContextConfig(BaseModel):
    """Context retrieval configuration."""

    semantic: Literal["auto", "always", "never"] = "auto"
    topup_recent: bool = True

    model_config = {"extra": "ignore"}


class OrgsConfig(BaseModel):
    """Org/company scope configuration.

    ``remotes`` maps a git remote owner (e.g. ``Sunrise-Robotics``) to a
    canonical org slug. ``overrides`` maps a canonicalised project name to an
    org, for forks/mirrors or edge cases the remote can't disambiguate.
    ``default`` is the org used when a repo has no git remote.
    """

    remotes: dict[str, str] = Field(default_factory=dict)
    overrides: dict[str, str] = Field(default_factory=dict)
    default: str = "personal"

    model_config = {"extra": "ignore"}

    @field_validator("remotes", "overrides")
    @classmethod
    def orgs_are_slugs(cls, value: dict[str, str]) -> dict[str, str]:
        """Check the mapped orgs at load time.

        An unchecked value here reached ``validate_org`` on every save and
        search, so one bad entry turned every call into an opaque internal
        error that said nothing about the config.
        """
        return {key: validate_org_slug(org) for key, org in value.items()}

    @field_validator("default")
    @classmethod
    def default_is_a_slug(cls, value: str) -> str:
        return validate_org_slug(value)


class ProjectsConfig(BaseModel):
    """Project canonicalization configuration.

    ``aliases`` maps a project name to its canonical name, merging genuinely
    different strings for the same work (e.g. ``grafana-usage-report`` →
    ``grafana-usage-automation``). Keys are matched after normalisation, so
    any casing/spelling of the same name hits the same alias; values should
    be the canonical name and are normalised on application.
    """

    aliases: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


class DedupConfig(BaseModel):
    """Near-duplicate detection on save.

    ``threshold`` is the minimum cosine similarity (computed from the vectors)
    at which a new memory triggers a ``near_duplicate`` warning against an
    existing one. Raise it towards 1.0 to warn less. Warnings never block
    a save.
    """

    threshold: float = 0.92

    model_config = {"extra": "ignore"}


class UsageConfig(BaseModel):
    """Lookup recording — which memories agents actually retrieve.

    Every MCP lookup (search, context, details, journey and artifact reads)
    is recorded with the memories it returned, so ``arcane analyze usage``
    can show what is used, what is never recalled and which searches find
    nothing. ``log_queries`` keeps the (redacted) search text; rows older than
    ``retention_days`` are pruned when the MCP server starts.
    """

    enabled: bool = True
    log_queries: bool = True
    retention_days: int = 180

    model_config = {"extra": "ignore"}


class ArcaneConfig(BaseModel):
    """Top-level Arcane configuration."""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    orgs: OrgsConfig = Field(default_factory=OrgsConfig)
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    usage: UsageConfig = Field(default_factory=UsageConfig)

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
    """Load ``ArcaneConfig`` from a YAML file, falling back to defaults when absent.

    A file that exists but cannot be used raises :class:`ConfigError` naming
    the file and the problem. Silently falling back to defaults would be worse
    than stopping: a dropped ``orgs`` mapping sends memories to a different
    org, where scoped recall will not find them again.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return ArcaneConfig()
    except OSError as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping of settings, not {type(data).__name__}")

    try:
        return ArcaneConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"{path} has invalid settings — {problems}") from exc
