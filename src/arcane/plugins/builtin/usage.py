"""Usage intelligence plugin — what agents actually recall from the store.

Reads the lookup log the MCP server records (``retrievals``) and reports
lookups per agent and tool, searches that found nothing (gaps in memory), how
often a recalled memory was then opened or updated, the most recalled
memories and, once there is enough history, memories nothing ever returned.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from arcane.infra.db.retrieval_repo import RetrievalRepository

# A memory counts as "never recalled" only if it existed for this long and the
# log has covered at least this long; before that the number is just noise.
NEVER_RECALLED_DAYS = 30


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


class UsageAnalyzer:
    name = "usage"

    def __init__(
        self, retrieval_repo: RetrievalRepository | None = None, days: int = 30, org: str | None = None
    ) -> None:
        self.org = org
        self.retrieval_repo = retrieval_repo
        self.days = days

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

    def analyze(self, project: str) -> list[dict[str, Any]]:
        repo = self.retrieval_repo
        if repo is None:
            return []
        first = repo.first_recorded(org=self.org)
        if first is None:
            return [
                self._insight(
                    "usage",
                    "Usage: no lookups recorded yet",
                    "The MCP server records each lookup from now on. Run this again after a few sessions.",
                    "info",
                    project,
                )
            ]

        days = self.days
        clients = repo.by_client(days, org=self.org)
        lookups = sum(c["lookups"] for c in clients)
        sessions = sum(c["sessions"] for c in clients)
        searches = repo.searches(days, org=self.org)
        follow = repo.follow_through(days, org=self.org)
        replaced = repo.replaced_hits(days, org=self.org)
        covered_days = (datetime.now(timezone.utc) - datetime.fromisoformat(first)).days

        lines = [
            f"Last {days} days: {lookups} lookups in {sessions} sessions (recording since {first[:10]}).",
            "",
            "By agent:",
            *[f"  {c['client']}: {c['lookups']} lookups, {c['sessions']} sessions" for c in clients],
            "",
            "By tool:",
            *[f"  {t['tool']}: {t['lookups']}" for t in repo.by_tool(days, org=self.org)],
            "",
            f"Searches with text: {searches['total']}, possible gaps: {searches['gaps']} "
            f"({_pct(searches['gaps'], searches['total'])}; {searches['empty']} returned nothing, the rest "
            "only weak matches with none of the search's key words).",
            f"Recall lookups followed by opening or updating a returned memory: {follow['followed']} "
            f"of {follow['total']} ({_pct(follow['followed'], follow['total'])}).",
            f"Lookups that returned a replaced (superseded) memory: {replaced['lookups']} ({replaced['hits']} hits).",
        ]
        top = repo.top_memories(days, org=self.org)
        if top:
            lines += ["", "Most recalled:"]
            lines += [f"  {m['hits']}x  {m['title']} ({m['project'] or 'no project'}) [{m['id'][:8]}]" for m in top]

        insights = [
            self._insight(
                "usage",
                f"Usage: {lookups} lookups in {days} days, {_pct(searches['gaps'], searches['total'])} "
                "of searches were possible gaps",
                "\n".join(lines),
                "info",
                project,
            )
        ]

        gaps = repo.gap_queries(days, org=self.org)
        if gaps:
            body = ["Searches where no memory held the key words (knowledge worth saving, or a naming mismatch):"]
            body += [
                f'  {q["times"]}x  "{q["query"]}" ({q["project"] or "no project"}'
                f"{', nothing returned' if not q['results'] else ''})"
                for q in gaps
            ]
            insights.append(
                self._insight(
                    "usage_gaps",
                    f"{searches['gaps']} search(es) found nothing relevant in {days} days",
                    "\n".join(body),
                    "warning",
                    project,
                )
            )

        if covered_days >= NEVER_RECALLED_DAYS:
            never = repo.never_recalled(NEVER_RECALLED_DAYS, org=self.org)
            if never["count"]:
                body = [
                    f"{never['count']} of {never['eligible']} memories older than {NEVER_RECALLED_DAYS} days "
                    f"have not been returned by any lookup since {first[:10]}. By project:"
                ]
                body += [f"  {p['project']}: {p['n']}" for p in never["by_project"]]
                body.append("Candidates to merge, improve or let expire (ttl_days).")
                insights.append(
                    self._insight(
                        "usage_never_recalled",
                        f"{never['count']} memories never recalled ({_pct(never['count'], never['eligible'])})",
                        "\n".join(body),
                        "info",
                        project,
                    )
                )
        return insights
