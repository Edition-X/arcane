"""Linear ingestion plugin — imports tickets as artifacts."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

import httpx


class LinearIngestionPlugin:
    name = "linear"

    def __init__(
        self,
        api_key: str | None = None,
        team_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        self.team_id = team_id

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        issues = self._fetch_issues()
        artifacts: list[dict[str, Any]] = []

        for issue in issues:
            created = _parse_iso(issue.get("createdAt", ""))
            if since and created and created < since:
                continue

            labels_nodes = issue.get("labels", {}).get("nodes", [])
            labels = [node["name"] for node in labels_nodes]
            state_name = issue.get("state", {}).get("name", "Unknown")
            assignee_name = (issue.get("assignee") or {}).get("name")

            artifacts.append({
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
            })

        return artifacts

    def _fetch_issues(self) -> list[dict[str, Any]]:
        """Fetch issues from Linear GraphQL API."""
        query = """
        query($teamId: String, $first: Int) {
            issues(
                filter: { team: { key: { eq: $teamId } } }
                first: $first
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
            }
        }
        """
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                "https://api.linear.app/graphql",
                headers=headers,
                json={"query": query, "variables": {"teamId": self.team_id, "first": 50}},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("issues", {}).get("nodes", [])
        except Exception:
            return []

    def supports_incremental(self) -> bool:
        return True


def _parse_iso(dt_str: str) -> datetime | None:
    """Parse ISO datetime string."""
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
