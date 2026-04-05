"""GitHub Actions ingestion plugin — imports CI runs as artifacts."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GHAIngestionPlugin:
    name = "github_actions"

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        per_page: int = 30,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.per_page = per_page

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        runs = self._fetch_runs()
        artifacts: list[dict[str, Any]] = []

        for run in runs:
            created = _parse_iso(run["created_at"])
            if since and created and created < since:
                continue

            conclusion = run.get("conclusion") or run.get("status", "unknown")
            branch = run.get("head_branch", "unknown")
            title = f"{run.get('name', 'CI')} #{run['id']} [{conclusion}] on {branch}"

            artifacts.append({
                "id": str(uuid.uuid4()),
                "artifact_type": "ci_run",
                "external_id": str(run["id"]),
                "title": title,
                "url": run.get("html_url"),
                "project": project,
                "created_at": run["created_at"],
                "raw_data": {
                    "run_id": run["id"],
                    "name": run.get("name"),
                    "conclusion": conclusion,
                    "status": run.get("status"),
                    "head_branch": branch,
                    "head_sha": run.get("head_sha"),
                    "run_attempt": run.get("run_attempt", 1),
                    "event": run.get("event"),
                    "created_at": run["created_at"],
                    "updated_at": run.get("updated_at"),
                },
            })

        return artifacts

    def _fetch_runs(self) -> list[dict[str, Any]]:
        """Fetch workflow runs from GitHub API."""
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/runs"
        try:
            resp = httpx.get(url, headers=headers, params={"per_page": self.per_page}, timeout=15)
            resp.raise_for_status()
            return resp.json().get("workflow_runs", [])
        except httpx.HTTPStatusError as exc:
            logger.warning("GitHub API returned %s for %s", exc.response.status_code, url)
            return []
        except httpx.RequestError as exc:
            logger.warning("Network error fetching GHA runs: %s", exc)
            return []

    def supports_incremental(self) -> bool:
        return True


def _parse_iso(dt_str: str) -> datetime | None:
    """Parse ISO datetime string."""
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
