"""Git ingestion plugin — imports commits and branches as artifacts."""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any


# Use record separator to cleanly delimit commits
_RS = "\x1e"  # record separator
_FS = "\x1f"  # field separator


class GitIngestionPlugin:
    name = "git"

    def __init__(self, repo_path: str | None = None, max_count: int = 100) -> None:
        self.repo_path = repo_path or os.getcwd()
        self.max_count = max_count

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        if not os.path.isdir(self.repo_path):
            return []

        git_dir = os.path.join(self.repo_path, ".git")
        if not os.path.isdir(git_dir):
            return []

        # Use two commands: one for metadata, one for files per commit
        format_str = f"{_RS}%H{_FS}%s{_FS}%b{_FS}%an{_FS}%aI"
        cmd = [
            "git", "log",
            f"--max-count={self.max_count}",
            f"--format={format_str}",
        ]

        if since:
            cmd.append(f"--since={since.isoformat()}")

        try:
            result = subprocess.run(
                cmd, cwd=self.repo_path, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        # Parse commits from metadata
        commits = self._parse_metadata(result.stdout)
        if not commits:
            return []

        # Get files changed per commit using --name-only --diff-filter
        for commit in commits:
            commit["files_changed"] = self._get_files_changed(commit["sha"])

        # Get current branch
        current_branch = self._get_branch()

        artifacts: list[dict[str, Any]] = []
        for c in commits:
            artifacts.append({
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
            })

        return artifacts

    def _parse_metadata(self, output: str) -> list[dict[str, Any]]:
        """Parse git log output using record separator."""
        commits: list[dict[str, Any]] = []
        for record in output.split(_RS):
            record = record.strip()
            if not record:
                continue
            parts = record.split(_FS)
            if len(parts) < 5:
                continue
            commits.append({
                "sha": parts[0].strip(),
                "title": parts[1].strip(),
                "body": parts[2].strip(),
                "author": parts[3].strip(),
                "date": parts[4].strip(),
            })
        return commits

    def _get_files_changed(self, sha: str) -> list[str]:
        """Get list of files changed in a commit."""
        try:
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
                cwd=self.repo_path, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f.strip()]
        except Exception:
            pass
        return []

    def _get_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path, capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def supports_incremental(self) -> bool:
        return True
