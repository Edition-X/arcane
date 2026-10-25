"""Linear ingestion plugin — imports tickets as artifacts."""

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

_LINEAR_GQL_URL = "https://api.linear.app/graphql"
_PAGE_SIZE = 50
_MAX_PAGES = 20
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 2.0  # seconds, doubles each attempt


class LinearIngestionPlugin:
    """Ingest tickets from Linear."""

    name = "linear"

    def __init__(
        self,
        api_key: str | None = None,
        team_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        self.team_id = team_id
        self._last_error = ""
        self.warnings: list[str] = []

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            raise IngestionError("LINEAR_API_KEY is not set, so Linear issues cannot be fetched.")
        issues = self._fetch_all_issues()
        artifacts: list[dict[str, Any]] = []

        for issue in issues:
            created = _parse_iso(issue.get("createdAt", ""))
            if since and created and created < since:
                continue

            labels_nodes = issue.get("labels", {}).get("nodes", [])
            labels = [node["name"] for node in labels_nodes]
            state_name = issue.get("state", {}).get("name", "Unknown")
            assignee_name = (issue.get("assignee") or {}).get("name")

            artifacts.append(
                {
                    "id": str(uuid.uuid4()),
                    "artifact_type": "linear_ticket",
                    "external_id": issue.get("identifier", issue["id"]),
                    "title": issue["title"],
                    "url": issue.get("url"),
                    "project": project,
                    "created_at": issue.get("createdAt", ""),
                    "raw_data": {
                        "linear_id": issue["id"],
                        "identifier": issue.get("identifier"),
                        "state": state_name,
                        "description": issue.get("description", ""),
                        "labels": labels,
                        "assignee": assignee_name,
                        "priority": issue.get("priority"),
                        "estimate": issue.get("estimate"),
                        "created_at": issue.get("createdAt"),
                        "updated_at": issue.get("updatedAt"),
                    },
                }
            )

        return artifacts

    def _fetch_all_issues(self) -> list[dict[str, Any]]:
        """Fetch all issues with cursor-based pagination (up to _MAX_PAGES)."""
        all_issues: list[dict[str, Any]] = []
        cursor: str | None = None
        more = False

        with httpx.Client(timeout=15) as client:
            for page in range(_MAX_PAGES):
                result = self._fetch_page(client, cursor)
                if result is None:
                    raise IngestionError(
                        f"Linear issues for team {self.team_id} could not be fetched after "
                        f"{_RETRY_ATTEMPTS} attempts ({self._last_error})."
                    )

                nodes = result.get("nodes", [])
                all_issues.extend(nodes)

                page_info = result.get("pageInfo", {})
                cursor = page_info.get("endCursor")
                more = bool(page_info.get("hasNextPage") and cursor)
                if not more:
                    break

                logger.debug("Linear: fetched page %d (%d issues so far)", page + 1, len(all_issues))

        if more:
            self.warnings.append(
                f"Stopped after {_MAX_PAGES} pages: only {len(all_issues)} issues of team {self.team_id} were read."
            )
        return all_issues

    def _fetch_page(self, client: httpx.Client, after: str | None = None) -> dict[str, Any] | None:
        """Fetch a single page of issues with retry + exponential back-off."""
        query = """
        query($teamId: String, $first: Int, $after: String) {
            issues(
                filter: { team: { key: { eq: $teamId } } }
                first: $first
                after: $after
                orderBy: createdAt
            ) {
                nodes {
                    id
                    identifier
                    title
                    state { name }
                    url
                    createdAt
                    updatedAt
                    description
                    labels { nodes { name } }
                    assignee { name }
                    priority
                    estimate
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        variables: dict[str, Any] = {"teamId": self.team_id, "first": _PAGE_SIZE}
        if after:
            variables["after"] = after

        delay = _RETRY_BACKOFF
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                resp = client.post(_LINEAR_GQL_URL, headers=headers, json={"query": query, "variables": variables})
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    logger.warning("Linear rate-limited; waiting %.1fs (attempt %d)", retry_after, attempt)
                    self._last_error = "HTTP 429, rate limited"
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("errors"):
                    # GraphQL reports bad keys and unknown teams in a 200 response.
                    self._last_error = "; ".join(str(e.get("message", e)) for e in data["errors"])
                    return None
                result: dict[str, Any] | None = (data.get("data") or {}).get("issues")
                return result
            except httpx.HTTPStatusError as exc:
                self._last_error = f"HTTP {exc.response.status_code}"
                logger.warning("Linear API error %s (attempt %d)", exc.response.status_code, attempt)
            except httpx.RequestError as exc:
                self._last_error = f"network error: {exc}"
                logger.warning("Linear network error: %s (attempt %d)", exc, attempt)

            if attempt < _RETRY_ATTEMPTS:
                time.sleep(delay)
                delay *= 2

        logger.error("Linear: all %d attempts failed", _RETRY_ATTEMPTS)
        return None

    def supports_incremental(self) -> bool:
        return True


def _parse_iso(dt_str: str) -> datetime | None:
    """Parse ISO datetime string."""
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
