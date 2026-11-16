"""Where a memory came from: the code state and the agent session that saved it.

Captured by the server on every save, with no effort from the agent, so a
memory can be traced to a commit and a conversation later (``arcane why``).
Every field is ``None`` when it is unknown: a folder that is not a git repo,
or a client that tells the server nothing about its session.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from arcane.domain.scope import _git


class Provenance(BaseModel):
    """Queryable origin fields stored on a memory row."""

    commit_sha: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    session_id: str | None = None
    thread_id: str | None = None

    def without_git(self) -> Provenance:
        """The same session, with no code state: the save was not about this checkout."""
        return self.model_copy(update={"commit_sha": None, "branch": None, "dirty": None})


def git_state(cwd: str) -> tuple[str | None, str | None, bool | None]:
    """``(commit_sha, branch, dirty)`` of HEAD in *cwd*; all ``None`` outside a repo.

    One git call, with ``--ignore-submodules`` and ``--untracked-files=no`` so it
    takes a few ms in a large repo and a save is not slowed. A detached HEAD
    gives the SHA and no branch. ``dirty`` means tracked files differ from HEAD;
    untracked files do not count. An unborn branch has no commit, so it gives a
    branch and no SHA. Never raises.
    """
    out = _git(
        cwd,
        "status",
        "--porcelain=v2",
        "--branch",
        "--untracked-files=no",
        "--ignore-submodules=all",
    )
    if out is None:
        return None, None, None
    sha: str | None = None
    branch: str | None = None
    dirty = False
    for line in out.splitlines():
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
    meta: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Provenance:
    """Collect the origin of a save made from *cwd*.

    *meta* is the ``_meta`` of the tool call. Only ids a client has been seen to
    send are read:

    - Codex puts ``sessionId`` and ``threadId`` in every call's ``_meta``.
    - Claude Code sends no session id in ``_meta``; its ``CLAUDE_CODE_SESSION_ID``
      is in the environment the server was started with.
    - T3 Code sets ``T3CODE_THREAD_ID`` in that environment.

    The environment is read when the server starts, so it is the session that
    started the server. If Claude Code runs ``/clear`` or resumes, the server
    keeps running and ``CLAUDE_CODE_SESSION_ID`` goes stale until the next server
    start, so a per-call ``_meta`` session id wins over it. The thread id is the
    other way round: the T3 thread is the one that can be opened, and it does not
    change while the server runs, so it wins over a client's own ``threadId``.
    """
    env = os.environ if env is None else env
    meta = meta or {}
    sha, branch, dirty = git_state(cwd)
    return Provenance(
        commit_sha=sha,
        branch=branch,
        dirty=dirty,
        session_id=_first(meta.get("sessionId"), env.get("CLAUDE_CODE_SESSION_ID")),
        thread_id=_first(env.get("T3CODE_THREAD_ID"), meta.get("threadId")),
    )
