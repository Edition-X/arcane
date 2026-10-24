"""Store health audit intelligence plugin.

Turns the external self-audit SQL battery into a first-class ``analyze
health`` call: recall-integrity checks (project fragmentation, orphan
memories, duplicate titles), journey hygiene, and lifecycle-adoption
metrics, emitted as insights.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from arcane.domain.scope import canonicalize_project
from arcane.infra.db.journey_repo import IDLE_JOURNEY_DAYS, JourneyRepository
from arcane.infra.db.memory_repo import MemoryRepository


class HealthAuditor:
    name = "health"

    def __init__(
        self,
        memory_repo: MemoryRepository | None = None,
        journey_repo: JourneyRepository | None = None,
        aliases: dict[str, str] | None = None,
        stale_days: int = IDLE_JOURNEY_DAYS,
        org: str | None = None,
    ) -> None:
        self.memory_repo = memory_repo
        self.journey_repo = journey_repo
        self.aliases = aliases or {}
        self.stale_days = stale_days
        self.org = org

    def _insight(self, insight_type: str, title: str, body: str, severity: str, project: str) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "insight_type": insight_type,
            "title": title,
            "body": body,
            "severity": severity,
            "project": project,
            "metadata": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _fragmentation_clusters(self, projects: list[dict[str, Any]]) -> list[list[str]]:
        """Group raw project names that canonicalize to the same slug."""
        groups: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in projects:
            raw = row["project"] or ""
            if not raw:
                continue
            org = row.get("org") or ""
            groups[(org, canonicalize_project(raw, self.aliases))].add(raw)
        return [sorted(names) for names in groups.values() if len(names) > 1]

    def analyze(self, project: str) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []

        stats: dict[str, Any] = self.memory_repo.stats(org=self.org) if self.memory_repo else {}
        total = stats.get("total", 0)

        # Fragmentation — the same repo living under several project strings.
        clusters = self._fragmentation_clusters(stats.get("projects", []))
        if clusters:
            lines = ["Project names that resolve to the same canonical project:"]
            for cluster in clusters:
                lines.append("  " + " / ".join(f"'{name}'" for name in cluster))
            lines.append("Heal with: arcane merge-projects <src> <dest> --apply")
            insights.append(
                self._insight(
                    "health_fragmentation",
                    f"Recall risk: {len(clusters)} fragmented project cluster(s)",
                    "\n".join(lines),
                    "warning",
                    project,
                )
            )

        # Only legacy rows with neither org nor project are unassigned. Org and
        # global memories intentionally have an empty project and remain visible.
        empty = stats.get("empty_project", 0)
        if empty:
            insights.append(
                self._insight(
                    "health_empty_project",
                    f"{empty} legacy memories have no org or project",
                    f"{empty} memories have neither an org nor a project and are invisible to "
                    "project-scoped context and search. Reassign them with "
                    "arcane merge-projects '' <project> --apply.",
                    "warning",
                    project,
                )
            )

        # Duplicate titles — the exact-title merge on save should prevent these.
        dups = stats.get("duplicate_titles", [])
        if dups:
            listed = ", ".join(
                f"'{d['title']}' x{d['cnt']} ({d.get('org') or 'unassigned'}/{d.get('project') or '*'})"
                for d in dups[:5]
            )
            insights.append(
                self._insight(
                    "health_duplicate_titles",
                    f"{len(dups)} duplicated memory title(s)",
                    f"Titles stored more than once in the same org/project scope: {listed}. "
                    "Merge or delete the extras.",
                    "warning",
                    project,
                )
            )

        # Journey hygiene — active journeys nobody has touched in weeks.
        stale = self.journey_repo.list_stale_active(days=self.stale_days, org=self.org) if self.journey_repo else []
        if stale:
            listed = ", ".join(f"'{j['title']}' (started {j['started_at'][:10]})" for j in stale[:5])
            insights.append(
                self._insight(
                    "health_stale_journeys",
                    f"{len(stale)} journey(s) stuck in active",
                    f"No update for more than {self.stale_days} days: {listed}. "
                    "Complete them with a summary or abandon them.",
                    "warning",
                    project,
                )
            )

        # Summary — always emitted, so a healthy store still reports a pulse.
        ttl_pct = (stats.get("ttl_set", 0) / total * 100) if total else 0.0
        conf_pct = (stats.get("confidence_set", 0) / total * 100) if total else 0.0
        cat_mix = ", ".join(f"{c['category'] or 'none'}: {c['cnt']}" for c in stats.get("categories", [])[:8])
        body = "\n".join(
            [
                f"Store health for {self.org or 'the whole vault'} (reported against '{project}'):",
                "",
                f"  Memories:            {total}",
                f"  Project scopes:      {sum(bool(row['project']) for row in stats.get('projects', []))}",
                f"  Category mix:        {cat_mix or 'n/a'}",
                f"  TTL adoption:        {ttl_pct:.0f}%",
                f"  Confidence adoption: {conf_pct:.0f}%",
                f"  Open findings:       {len(insights)}",
            ]
        )
        insights.append(
            self._insight(
                "health",
                f"Health: {total} memories, {len(insights)} finding(s)",
                body,
                "info",
                project,
            )
        )
        return insights
