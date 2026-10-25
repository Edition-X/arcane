"""GitHub Actions ingestion plugin — imports CI runs as artifacts."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

from arcane.plugins.protocols import IngestionError

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 2.0  # seconds, doubles each attempt
_MAX_PAGES = 10
# A rate limit that resets further off than this fails the import instead of
# holding the caller (often an MCP tool call) for up to an hour.
_MAX_RATE_LIMIT_WAIT = 60.0


class GHAIngestionPlugin:
    """Ingest CI runs from GitHub Actions."""

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
        self._last_error = ""
        self._attempts = 0
        self.warnings: list[str] = []

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

            artifacts.append(
                {
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
                }
            )

        return artifacts

    def _fetch_all_runs(self) -> list[dict[str, Any]]:
        """Fetch workflow runs, newest first, with Link-header pagination up to _MAX_PAGES."""
        all_runs: list[dict[str, Any]] = []
        url: str | None = f"{_GH_API}/repos/{self.owner}/{self.repo}/actions/runs"
        params: dict[str, Any] | None = {"per_page": self.per_page}
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        with httpx.Client(headers=headers, timeout=15) as client:
            for page in range(_MAX_PAGES):
                if url is None:
                    break
                result = self._fetch_page(client, url, params)
                if result is None:
                    hint = "" if self.token else " GITHUB_TOKEN is not set, which private repos need."
                    attempts = f"{self._attempts} attempt{'s' if self._attempts != 1 else ''}"
                    raise IngestionError(
                        f"GitHub Actions runs for {self.owner}/{self.repo} could not be fetched after "
                        f"{attempts} ({self._last_error}).{hint}"
                    )

                runs, url = result
                all_runs.extend(runs)
                # The next URL carries the whole query. Pass None, not {}: httpx
                # replaces a URL's query with an empty params dict, which made
                # every later page re-fetch page 1.
                params = None
                logger.debug("GHA: fetched page %d (%d runs so far)", page + 1, len(all_runs))

        if url is not None:
            self.warnings.append(
                f"Stopped after {_MAX_PAGES} pages: only the newest {len(all_runs)} runs of "
                f"{self.owner}/{self.repo} were read."
            )
        return all_runs

    def _fetch_page(
        self, client: httpx.Client, url: str, params: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], str | None] | None:
        """Fetch a single page; returns (runs, next_url) or None on hard failure."""
        delay = _RETRY_BACKOFF
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            self._attempts = attempt
            try:
                resp = client.get(url, params=params)

                wait = _rate_limit_wait(resp, delay)
                if wait is not None:
                    self._last_error = f"HTTP {resp.status_code}, rate limited"
                    if wait > _MAX_RATE_LIMIT_WAIT:
                        self._last_error += f"; the limit resets in {wait / 60:.0f} min"
                        return None
                    logger.warning("GitHub rate-limited; waiting %.1fs (attempt %d)", wait, attempt)
                    time.sleep(wait)
                    delay *= 2
                    continue

                if resp.status_code in (401, 403, 404):
                    # Bad or missing credentials, or no such repo: retrying cannot help.
                    self._last_error = f"HTTP {resp.status_code}"
                    return None

                resp.raise_for_status()
                runs = resp.json().get("workflow_runs", [])
                next_url = _parse_link_header(resp.headers.get("Link", ""))
                return runs, next_url

            except httpx.HTTPStatusError as exc:
                self._last_error = f"HTTP {exc.response.status_code}"
                logger.warning("GitHub API error %s (attempt %d)", exc.response.status_code, attempt)
            except httpx.RequestError as exc:
                self._last_error = f"network error: {exc}"
                logger.warning("GitHub network error: %s (attempt %d)", exc, attempt)

            if attempt < _RETRY_ATTEMPTS:
                time.sleep(delay)
                delay *= 2

        logger.error("GHA: all %d attempts failed for %s", _RETRY_ATTEMPTS, url)
        return None

    def supports_incremental(self) -> bool:
        return True


def _rate_limit_wait(resp: httpx.Response, default: float) -> float | None:
    """Seconds to wait when *resp* is a rate limit, else None.

    GitHub answers both 429 and 403 for rate limits; a 403 is only one when it
    says so with Retry-After or an exhausted X-RateLimit-Remaining. Any other
    403 is a permissions failure.
    """
    if resp.status_code not in (403, 429):
        return None
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        return float(retry_after)
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset")
        return max(0.0, float(reset) - time.time()) if reset else default
    return default if resp.status_code == 429 else None


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
