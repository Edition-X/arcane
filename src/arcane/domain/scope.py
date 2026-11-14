"""Scope resolution — map a working directory to a (org, project) scope.

Arcane organises memory in three layers: ``global`` (universal to the user),
``org`` (a company, shared across all its repos) and ``project`` (a single
repo). The org is resolved from the git remote owner, with a config override.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, field_validator

from arcane.infra.config import ArcaneConfig, validate_org_slug

GLOBAL_ORG = "global"
DEFAULT_ORG = "personal"

# Org names Arcane reserves for the global/personal layers.
RESERVED_ORGS = {GLOBAL_ORG, DEFAULT_ORG}

_REMOTE_RE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")

# Every MCP call resolves scope from the working directory, and the git
# subprocess behind it was most of a call's latency. Remotes almost never
# change mid-session, so a lookup is reused for this many seconds.
REMOTE_CACHE_TTL_SECONDS = 60.0
_remote_cache: dict[str, tuple[float, tuple[str | None, str | None]]] = {}
_remote_cache_lock = threading.Lock()


class Scope(BaseModel):
    """The resolved scope for a session: which org and project it belongs to."""

    org: str = DEFAULT_ORG
    project: str = ""

    @field_validator("org")
    @classmethod
    def safe_org(cls, value: str) -> str:
        return validate_org(value)


def validate_org(value: str) -> str:
    """Accept only canonical org slugs, so an org can safely name a directory.

    The rule itself lives in ``infra.config``, which validates configured orgs
    at load time; this is the name the rest of the code calls it by.
    """
    return validate_org_slug(value)


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

    A repo with no usable remote gives ``(None, <main checkout name>)`` so its
    worktrees share one project. Best-effort and fast: a short timeout, and any
    failure (not a repo, git missing) resolves to ``(None, None)`` so the caller
    falls back cleanly.
    Results are cached per directory for ``REMOTE_CACHE_TTL_SECONDS``.
    """
    now = time.monotonic()
    with _remote_cache_lock:
        cached = _remote_cache.get(cwd)
    if cached is not None and now - cached[0] < REMOTE_CACHE_TTL_SECONDS:
        return cached[1]
    info = _read_git_remote(cwd)
    with _remote_cache_lock:
        _remote_cache[cwd] = (now, info)
    return info


def clear_remote_cache() -> None:
    """Forget cached git remote lookups (tests, or after changing a remote)."""
    with _remote_cache_lock:
        _remote_cache.clear()


def _git(cwd: str, *args: str) -> str | None:
    """Run a short git command in *cwd*; its stripped stdout, or ``None`` on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.strip()


def _local_repo_name(cwd: str) -> str | None:
    """Name of the main checkout of the repo containing *cwd*, or ``None``.

    For a repo with no remote, the directory name is all there is to go on, and
    a worktree's directory (``~/.t3/worktrees/emergence/t3code-72abab4d``) says
    nothing about the repo. The shared git dir does: ``<main checkout>/.git``.
    """
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    common = os.path.normpath(common)
    if os.path.basename(common) == ".git":
        return os.path.basename(os.path.dirname(common)) or None
    # A bare repo: its directory is the name, minus a conventional .git suffix.
    name = os.path.basename(common)
    return name.removesuffix(".git") or None


def _read_git_remote(cwd: str) -> tuple[str | None, str | None]:
    url = _git(cwd, "remote", "get-url", "origin")
    if url:
        owner, repo = _parse_remote_url(url)
        if repo:
            return owner, repo
    return None, _local_repo_name(cwd)


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


# What a read can ask for. Omitted means auto: the project's own layers, widened
# to the org's other projects when the project is thin.
ReadScope = Literal["project", "org", "global", "all"]
READ_SCOPES: tuple[ReadScope, ...] = get_args(ReadScope)

# How far a search reads: ``layers`` is the project, org and global chain, ``org``
# adds every other project of the org, ``all`` reads every org, and ``auto`` picks
# ``org`` or ``layers`` by how thin the project is.
Reach = Literal["auto", "layers", "org", "all"]


@dataclass(frozen=True)
class ReadPlan:
    """The layers and reach a read covers, from a caller's ``scope``."""

    org: str
    project: str
    include_org: bool
    include_global: bool
    reach: Reach
    scope: ReadScope | None

    def nothing_found(self) -> str | None:
        """What to tell a caller whose search matched nothing, true to what was searched.

        ``None`` when every project of every org was already searched.
        """
        if self.scope == "all":
            return None
        if self.scope == "global":
            return "Nothing matched in global memories. Retry without scope, or with scope='all' to search every org."
        if self.scope == "org":
            return (
                f"Nothing matched among org '{self.org}' memories. "
                "Retry without scope, or with scope='all' to search every project in every org."
            )
        where = f"project '{self.project}'" if self.project else "this project"
        wider = (
            f"to include org '{self.org}' and its other projects, or scope='all' to search every project in every org"
        )
        if self.scope == "project":
            return f"Nothing matched in {where}. Retry without scope {wider}."
        if not self.include_org:
            return f"Nothing matched in {where} (include_org was false). Retry with include_org=true {wider}."
        layers = f"org '{self.org}' (every project)" + (" and global memories" if self.include_global else "")
        return f"Nothing matched in {layers}. Retry with scope='all' to search every project in every org."


def plan_read(
    scope: ReadScope | None, org: str, project: str, include_org: bool = True, include_global: bool = True
) -> ReadPlan:
    """Map a read ``scope`` to the org, project, layers and reach to search.

    Omitted scope keeps the caller's layers and lets the service widen when the
    project is thin, unless the caller turned the org layer off; an explicit
    scope never widens, except ``all``.
    """
    if scope is None:
        reach: Reach = "auto" if include_org else "layers"
        return ReadPlan(org, project, include_org, include_global, reach, scope)
    if scope == "project":
        return ReadPlan(org, project, False, False, "layers", scope)
    if scope == "org":
        return ReadPlan(org, "", True, False, "layers", scope)
    if scope == "global":
        return ReadPlan(GLOBAL_ORG, "", True, False, "layers", scope)
    if scope == "all":
        return ReadPlan(org, project, include_org, include_global, "all", scope)
    raise ValueError(f"Unknown scope '{scope}'. Valid values: {', '.join(READ_SCOPES)}.")
