"""Why — the decisions and bugs behind a file or a commit."""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

from arcane.domain.scope import resolve_write_scope
from arcane.infra.git import git_output
from arcane.services.container import ServiceContainer

# Categories that answer "why is the code like this": the call made, and the fault fixed.
WHY_CATEGORIES = ("decision", "bug")
_SHA = re.compile(r"[0-9a-fA-F]{7,40}")


class WhyError(Exception):
    """The target is not something ``why`` can look up."""


def normalize_path(path: str) -> str:
    """Turn a path into the posix form memories are compared in: no ``./``, no ``..``, no ``//``."""
    return posixpath.normpath(path.strip().replace("\\", "/"))


def path_matches(stored: str, target: str) -> bool:
    """Whether a path saved in ``related_files`` names the same file as *target*.

    Memories hold repo-relative paths (``src/a.py``) and absolute ones
    (``/Users/me/code/repo/src/a.py``) side by side. *target* is repo-relative, or
    absolute when the file lies outside the repo. They match when they are equal,
    or when *stored* ends with *target* at a ``/`` boundary, so ``src/a.py`` finds
    ``/x/repo/src/a.py`` but ``a.py`` never finds ``src/data.py`` or ``src/xa.py``.
    Shared by any caller that looks up memories by file.
    """
    stored, target = normalize_path(stored), normalize_path(target)
    return stored == target or stored.endswith("/" + target.lstrip("/"))


@dataclass
class WhyResult:
    target: str
    kind: str  # "file" or "commit"
    commit: str | None = None
    files: list[str] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    superseded: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "kind": self.kind,
            "commit": self.commit,
            "files": self.files,
            "memories": self.memories,
            "superseded": self.superseded,
        }


def _git(cwd: str, *args: str) -> str | None:
    """Stripped stdout of ``git -C cwd <args>``, or None when git fails (see ``git_output``)."""
    out = git_output(cwd, *args)
    return None if out is None else out.strip()


class WhyService:
    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def why(self, target: str, *, everywhere: bool = False, cwd: str | None = None) -> WhyResult:
        """Find the decisions and bugs behind *target*, a file path or a commit.

        Args:
            target: A path, or 7+ hex characters that ``git rev-parse`` resolves to a
                commit in *cwd*'s repo.
            everywhere: Read every project instead of the current one.
            cwd: The directory to resolve paths, commits and the project from.

        Raises:
            WhyError: *target* looks like a commit that the repo does not have.
        """
        cwd = cwd or os.getcwd()
        root = _git(cwd, "rev-parse", "--show-toplevel") or cwd
        sha = _git(cwd, "rev-parse", "--verify", "--quiet", f"{target}^{{commit}}") if _SHA.fullmatch(target) else None
        if _SHA.fullmatch(target) and not sha and not os.path.exists(os.path.join(cwd, target)):
            raise WhyError(f"{target} is not a commit in this repository, and no such file exists.")

        scope = None if everywhere else resolve_write_scope(None, self.c.config, repo_path=cwd)
        if sha:
            names = self._touched(cwd, sha)
            result = WhyResult(target=target, kind="commit", commit=sha, files=[normalize_path(n) for n in names if n])
            rows = [dict(r, via="commit") for r in self._by_commit(sha, scope)]
        else:
            absolute = os.path.abspath(os.path.join(cwd, target))
            try:
                rel = os.path.relpath(absolute, root)
            except ValueError:  # another drive on Windows
                rel = ".."
            path = normalize_path(absolute if rel.startswith("..") else rel)
            result = WhyResult(target=target, kind="file", files=[path])
            rows = []
        seen = {r["id"] for r in rows}
        for r in self._by_files(result.files, scope):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(dict(r, via="file"))

        replaced = self.c.relationship_repo.superseded_by([r["id"] for r in rows])
        for row in rows:
            if row["id"] in replaced:
                row["superseded_by"] = replaced[row["id"]]
        # Commit matches first, then file matches; newest first within each.
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        rows.sort(key=lambda r: r["via"] != "commit")
        out = [self._entry(r, result.files) for r in rows]
        result.memories = [e for e in out if "superseded_by" not in e]
        result.superseded = [e for e in out if "superseded_by" in e]
        return result

    @staticmethod
    def _touched(cwd: str, sha: str) -> list[str]:
        """Files *sha* changed; for a merge, the files it brought in from the second parent onto the first."""
        parents = (_git(cwd, "rev-list", "--parents", "-n", "1", sha) or "").split()[1:]
        if len(parents) > 1:
            out = _git(cwd, "diff", "--name-only", f"{sha}^1", sha)
        else:
            out = _git(cwd, "show", "--name-only", "--format=", sha)
        return (out or "").splitlines()

    def _by_commit(self, sha: str, scope: Any) -> list[dict[str, Any]]:
        org, project = (None, None) if scope is None else (scope.org, scope.project)
        return self.c.memory_repo.by_commit_sha(sha, org, project)

    def _by_files(self, files: list[str], scope: Any) -> list[dict[str, Any]]:
        org, project = (None, None) if scope is None else (scope.org, scope.project)
        rows = self.c.memory_repo.why_candidates_for_files(
            [os.path.basename(f) for f in files], WHY_CATEGORIES, org, project
        )
        return [r for r in rows if any(path_matches(s, f) for s in r["related_files"] for f in files)]

    @staticmethod
    def _entry(row: dict[str, Any], files: list[str]) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": row["id"],
            "date": (row.get("created_at") or "")[:10],
            "project": row.get("project"),
            "org": row.get("org"),
            "category": row.get("category"),
            "title": row["title"],
            "what": row["what"],
            "why": row.get("why"),
            "via": row["via"],
            "matched_files": [s for s in row["related_files"] if any(path_matches(s, f) for f in files)],
        }
        if "superseded_by" in row:
            entry["superseded_by"] = row["superseded_by"]
        return entry
