"""Scope resolution — map a working directory to a (org, project) scope.

Arcane organises memory in three layers: ``global`` (universal to the user),
``org`` (a company, shared across all its repos) and ``project`` (a single
repo). The org is resolved from the git remote owner, with a config override.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping

from pydantic import BaseModel

from arcane.infra.config import ArcaneConfig

GLOBAL_ORG = "global"
DEFAULT_ORG = "personal"

# Org names Arcane reserves for the global/personal layers.
RESERVED_ORGS = {GLOBAL_ORG, DEFAULT_ORG}

_REMOTE_RE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


class Scope(BaseModel):
    """The resolved scope for a session: which org and project it belongs to."""

    org: str = DEFAULT_ORG
    project: str = ""


def slugify(name: str) -> str:
    """Lowercase, collapse non-alphanumeric runs to single dashes, trim dashes."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def canonicalize_project(name: str, aliases: Mapping[str, str] | None = None) -> str:
    """Normalise a project name. ``owner/repo`` collapses to the repo slug.

    When *aliases* is given, the normalised slug is mapped through it (keys
    are matched after normalisation, values are normalised on application) so
    genuinely different names for the same work resolve to one canonical name.
    """
    name = (name or "").strip()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    slug = slugify(name)
    if slug and aliases:
        lookup = {slugify(k): v for k, v in aliases.items()}
        if slug in lookup:
            slug = slugify(lookup[slug])
    return slug


def collapse_project_variant(explicit: str, resolved: str) -> str:
    """Collapse a worktree-style variant of *resolved* back to *resolved*.

    Agents often pass the working-directory name as the project. For a git
    worktree that is ``<repo>-<suffix>`` (``sunrise-robot-sw-inf613``), which
    would split memories away from ``sunrise-robot-sw``. When *explicit* is
    ``resolved + "-" + anything`` we return *resolved*; otherwise *explicit*
    is returned untouched so a deliberately different project still wins.
    """
    if not explicit or not resolved or explicit == resolved:
        return explicit
    if explicit.startswith(resolved + "-"):
        return resolved
    return explicit


def _parse_remote_url(url: str) -> tuple[str | None, str | None]:
    """Extract ``(owner, repo)`` from a git remote URL, or ``(None, None)``."""
    m = _REMOTE_RE.search((url or "").strip())
    if m:
        return m.group(1), m.group(2)
    return None, None


def git_remote_info(cwd: str) -> tuple[str | None, str | None]:
    """Return ``(owner, repo)`` from the ``origin`` remote, or ``(None, None)``.

    Best-effort and fast: a short timeout, and any failure (no repo, no remote,
    git missing) resolves to ``(None, None)`` so the caller falls back cleanly.
    """
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0 or not out.stdout.strip():
        return None, None
    return _parse_remote_url(out.stdout)


def resolve_scope(
    cwd: str,
    config: ArcaneConfig,
    *,
    _remote: tuple[str | None, str | None] | None = None,
) -> Scope:
    """Resolve the ``(org, project)`` scope for *cwd*.

    Org is the remote owner mapped through ``config.orgs.remotes`` (falling back
    to a slug of the owner), or ``config.orgs.default`` when there is no remote.
    A per-project ``overrides`` entry wins over everything. ``_remote`` is a test
    seam to inject ``(owner, repo)`` without invoking git.
    """
    owner, repo = _remote if _remote is not None else git_remote_info(cwd)

    aliases = config.projects.aliases
    if repo:
        project = canonicalize_project(repo, aliases)
    else:
        project = canonicalize_project(os.path.basename(os.path.normpath(cwd)), aliases) if cwd else ""

    if owner:
        org = config.orgs.remotes.get(owner) or config.orgs.remotes.get(owner.lower()) or slugify(owner)
    else:
        org = config.orgs.default or DEFAULT_ORG

    if project and project in config.orgs.overrides:
        org = config.orgs.overrides[project]

    return Scope(org=org or DEFAULT_ORG, project=project)


def resolve_write_scope(
    project: str | None,
    config: ArcaneConfig,
    *,
    repo_path: str | None = None,
    _remote: tuple[str | None, str | None] | None = None,
) -> Scope:
    """Resolve write scope, preserving explicit project names over repo defaults."""
    resolved = resolve_scope(repo_path or os.getcwd(), config, _remote=_remote)
    if project is None:
        return resolved
    slug = canonicalize_project(project, config.projects.aliases)
    return Scope(org=resolved.org, project=collapse_project_variant(slug, resolved.project))


def resolve_read_project(project: str | None, config: ArcaneConfig, cwd: str | None = None) -> str | None:
    """Canonicalise an explicit *project* for reads, collapsing worktree variants.

    Returns ``None`` when *project* is ``None`` so callers keep their existing
    "no filter" behaviour.
    """
    if project is None:
        return None
    resolved = resolve_scope(cwd or os.getcwd(), config)
    slug = canonicalize_project(project, config.projects.aliases)
    return collapse_project_variant(slug, resolved.project)
