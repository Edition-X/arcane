"""Where a memory came from: the code state and the agent session that saved it.

Captured by the server on every save, with no effort from the agent, so a
memory can be traced to a commit and a conversation later (``arcane why``).
Every field is ``None`` when it is unknown: a folder that is not a git repo,
or a client that tells the server nothing about its session.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from arcane.domain.scope import slugify

# MCP clientInfo.name slugs that are better known by another name.
_HARNESS_NAMES = {"codex-mcp-client": "codex"}


class Provenance(BaseModel):
    """Queryable origin fields stored on a memory row."""

    commit_sha: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    session_id: str | None = None
    thread_id: str | None = None
    harness: str | None = None


def git_state(cwd: str) -> tuple[str | None, str | None, bool | None]:
    """``(commit_sha, branch, dirty)`` of HEAD in *cwd*; all ``None`` outside a repo.

    One git call. ``--ignore-submodules`` and ``--untracked-files=no`` keep it
    to a few ms in a large repo with submodules, so a save is not slowed. A
    detached HEAD gives the SHA and no branch. ``dirty`` means tracked files
    differ from HEAD; untracked files do not count. An unborn branch has no
    commit, so it gives a branch and no SHA. Never raises.

    ``GIT_OPTIONAL_LOCKS=0`` stops ``git status`` refreshing the index, which
    takes ``index.lock``: the agent that called the save may be running its
    own git command in the same checkout at that moment.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                cwd,
                "status",
                "--porcelain=v2",
                "--branch",
                "--untracked-files=no",
                "--ignore-submodules=all",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    if out.returncode != 0:
        return None, None, None
    sha: str | None = None
    branch: str | None = None
    dirty = False
    for line in out.stdout.splitlines():
        if line.startswith("# branch.oid "):
            value = line.removeprefix("# branch.oid ")
            sha = None if value == "(initial)" else value
        elif line.startswith("# branch.head "):
            value = line.removeprefix("# branch.head ")
            branch = None if value == "(detached)" else value
        elif not line.startswith("#"):
            dirty = True
    return sha, branch, dirty


def _first(*values: Any) -> str | None:
    """The first of *values* that is a non-blank string, stripped; else ``None``."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def capture_provenance(
    cwd: str,
    *,
    client: str | None = None,
    meta: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Provenance:
    """Collect the origin of a save made from *cwd*.

    *client* is the MCP clientInfo name; *meta* is the ``_meta`` of the tool
    call. Only ids a client has been seen to send are read:

    - Codex puts ``sessionId`` and ``threadId`` in every call's ``_meta``.
    - Claude Code sends no session id in ``_meta``; its ``CLAUDE_CODE_SESSION_ID``
      is in the environment the server was started with.
    - T3 Code sets ``T3CODE_THREAD_ID`` in that environment.

    The environment is read when the server starts, so it is the session that
    started the server. If Claude Code runs ``/clear`` or resumes, the server
    keeps running and the id here goes stale until the next server start. A
    per-call ``_meta`` value is current, so it wins over the environment.
    """
    env = os.environ if env is None else env
    meta = meta or {}
    sha, branch, dirty = git_state(cwd)
    if client:
        harness: str | None = _HARNESS_NAMES.get(client, client)
    elif env.get("CLAUDECODE"):
        harness = "claude-code"
    else:
        harness = None
    return Provenance(
        commit_sha=sha,
        branch=branch,
        dirty=dirty,
        session_id=_first(meta.get("sessionId"), env.get("CLAUDE_CODE_SESSION_ID")),
        thread_id=_first(meta.get("threadId"), env.get("T3CODE_THREAD_ID")),
        harness=slugify(harness) if harness else None,
    )
