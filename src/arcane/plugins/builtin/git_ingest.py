"""Git ingestion plugin — imports commits and branches as artifacts."""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Record/field separators delimit commits and fields in git log output
_RS = "\x1e"  # record separator
_FS = "\x1f"  # field separator


class GitIngestionPlugin:
    name = "git"

    def __init__(self, repo_path: str | None = None, max_count: int = 100) -> None:
        self.repo_path = repo_path or os.getcwd()
        self.max_count = max_count

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        # No ".git" directory check: in a linked worktree ".git" is a file, and
        # git itself reports a non-repository through its exit code.
        if not os.path.isdir(self.repo_path):
            return []

        # One git call returns metadata and changed files for every commit.
        format_str = f"{_RS}%H{_FS}%s{_FS}%b{_FS}%an{_FS}%aI{_FS}"
        cmd = [
            "git",
            "log",
            "--no-color",
            "--name-only",
            f"--max-count={self.max_count}",
            f"--format={format_str}",
        ]

        if since:
            cmd.append(f"--since={since.isoformat()}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning("git log returned non-zero exit code %d", result.returncode)
                return []
        except subprocess.TimeoutExpired:
            logger.warning("git log timed out in %s", self.repo_path)
            return []
        except FileNotFoundError:
            logger.warning("git not found on PATH")
            return []

        commits = self._parse_log(result.stdout)
        if not commits:
            return []

        # Get current branch
        current_branch = self._get_branch()

        artifacts: list[dict[str, Any]] = []
        for c in commits:
            artifacts.append(
                {
                    "id": str(uuid.uuid4()),
                    "artifact_type": "commit",
                    "external_id": c["sha"],
                    "title": c["title"],
                    "url": None,
                    "project": project,
                    "created_at": c["date"],
                    "raw_data": {
                        "sha": c["sha"],
                        "body": c["body"],
                        "author": c["author"],
                        "date": c["date"],
                        "files_changed": c["files_changed"],
                        "branch": current_branch,
                    },
                }
            )

        return artifacts

    def _parse_log(self, output: str) -> list[dict[str, Any]]:
        """Parse ``git log --name-only`` output delimited by record/field separators."""
        commits: list[dict[str, Any]] = []
        for record in output.split(_RS):
            # Never strip the record itself: Python treats the separator
            # characters as whitespace and would eat the trailing field
            # separator of a commit with no changed files (e.g. a merge).
            if not record.strip():
                continue
            parts = record.split(_FS)
            if len(parts) < 6:
                continue
            commits.append(
                {
                    "sha": parts[0].strip(),
                    "title": parts[1].strip(),
                    "body": parts[2].strip(),
                    "author": parts[3].strip(),
                    "date": parts[4].strip(),
                    "files_changed": [line for line in parts[5].splitlines() if line.strip()],
                }
            )
        return commits

    def _get_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.debug("Could not determine current branch")
            return "unknown"

    def supports_incremental(self) -> bool:
        return True
