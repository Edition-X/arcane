"""Why — the decisions and bugs behind a file or a commit."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from arcane.domain.scope import resolve_write_scope
from arcane.infra.db.memory_repo import MemoryRepository
from arcane.services.container import ServiceContainer

# Categories that answer "why is the code like this": the call made, and the fault fixed.
WHY_CATEGORIES = ("decision", "bug")
_SHA = re.compile(r"[0-9a-fA-F]{7,40}")


class WhyError(Exception):
    """The target is not something ``why`` can look up."""


def normalize_path(path: str) -> str:
    """Turn a path into the posix form memories are compared in: no ``./``, no ``..``, no ``//``."""
    return PurePosixPath(os.path.normpath(path.strip().replace("\\", "/"))).as_posix()


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
    proc = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


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
            names = (_git(cwd, "show", "--name-only", "--format=", sha) or "").splitlines()
            result = WhyResult(target=target, kind="commit", commit=sha, files=[normalize_path(n) for n in names if n])
            rows = [dict(r, via="commit") for r in self._by_commit(sha, scope)]
        else:
            absolute = os.path.abspath(os.path.join(cwd, target))
            rel = os.path.relpath(absolute, root)
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

    def _by_commit(self, sha: str, scope: Any) -> list[dict[str, Any]]:
        where, params = self._where(scope)
        rows = self.c.db.fetchall(
            "SELECT m.* FROM memories m WHERE "
            "(m.commit_sha = ? OR (length(m.commit_sha) >= 7 AND ? LIKE m.commit_sha || '%')) "
            f"AND {where}",
            [sha, sha, *params],
        )
        return [self._decode(r) for r in rows]

    def _by_files(self, files: list[str], scope: Any) -> list[dict[str, Any]]:
        if not files:
            return []
        where, params = self._where(scope)
        marks = " OR ".join("m.related_files LIKE ? ESCAPE '\\'" for _ in files)
        likes = [
            "%" + os.path.basename(f).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for f in files
        ]
        categories = ",".join("?" * len(WHY_CATEGORIES))
        rows = self.c.db.fetchall(
            f"SELECT m.* FROM memories m WHERE m.category IN ({categories}) AND ({marks}) AND {where}",
            [*WHY_CATEGORIES, *likes, *params],
        )
        return [
            r for r in map(self._decode, rows) if any(path_matches(s, f) for s in r["related_files"] for f in files)
        ]

    @staticmethod
    def _where(scope: Any) -> tuple[str, list[Any]]:
        not_expired = MemoryRepository._not_expired_clause()
        if scope is None:
            return not_expired, []
        return f"m.org = ? AND m.project = ? AND {not_expired}", [scope.org, scope.project]

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        from arcane.infra.db.memory_repo import _process_row

        return _process_row(row)

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
