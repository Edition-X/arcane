"""GitHub Actions ingestion plugin — imports CI runs as artifacts."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 2.0  # seconds, doubles each attempt
_MAX_PAGES = 10


class GHAIngestionPlugin:
    name = "github_actions"

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        per_page: int = 100,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.per_page = per_page

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        runs = self._fetch_all_runs()
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

    def _fetch_all_runs(self) -> list[dict[str, Any]]:
        """Fetch all workflow runs with Link-header pagination."""
        all_runs: list[dict[str, Any]] = []
        url: str | None = (
            f"{_GH_API}/repos/{self.owner}/{self.repo}/actions/runs"
        )
        params: dict[str, Any] = {"per_page": self.per_page}

        for page in range(_MAX_PAGES):
            result = self._fetch_page(url, params)
            if result is None:
                break

            runs, next_url = result
            all_runs.extend(runs)

            if not next_url:
                break  # no more pages
            url = next_url
            params = {}  # next URL already has all query params
            logger.debug("GHA: fetched page %d (%d runs so far)", page + 1, len(all_runs))

        return all_runs

    def _fetch_page(
        self, url: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None] | None:
        """Fetch a single page; returns (runs, next_url) or None on hard failure."""
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        delay = _RETRY_BACKOFF
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                resp = httpx.get(url, headers=headers, params=params, timeout=15)

                if resp.status_code == 429 or resp.status_code == 403:
                    retry_after = float(
                        resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset-After", delay)
                    )
                    logger.warning(
                        "GitHub rate-limited (%s); waiting %.1fs (attempt %d)",
                        resp.status_code, retry_after, attempt,
                    )
                    time.sleep(retry_after)
                    delay *= 2
                    continue

                resp.raise_for_status()
                runs = resp.json().get("workflow_runs", [])
                next_url = _parse_link_header(resp.headers.get("Link", ""))
                return runs, next_url

            except httpx.HTTPStatusError as exc:
                logger.warning("GitHub API error %s (attempt %d)", exc.response.status_code, attempt)
            except httpx.RequestError as exc:
                logger.warning("GitHub network error: %s (attempt %d)", exc, attempt)

            if attempt < _RETRY_ATTEMPTS:
                time.sleep(delay)
                delay *= 2

        logger.error("GHA: all %d attempts failed for %s", _RETRY_ATTEMPTS, url)
        return None

    def supports_incremental(self) -> bool:
        return True


def _parse_link_header(header: str) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub Link header."""
    for part in header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            url_part = part.split(";")[0].strip()
            return url_part.strip("<>")
    return None


def _parse_iso(dt_str: str) -> datetime | None:
    """Parse ISO datetime string."""
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
