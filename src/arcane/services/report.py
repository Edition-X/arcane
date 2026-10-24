"""Work reports and per-org exports over the store.

``build_report`` answers "what did I do between these dates": milestones
shipped, decisions with their reasons, bugs fixed and investigations finished,
grouped by org and project. ``export_org`` dumps everything one org owns, so a
company's knowledge can be handed over or moved to another store.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from arcane import __version__
from arcane.services.container import ServiceContainer

REPORT_CATEGORIES = ("milestone", "decision", "bug")
SECTIONS = (
    ("milestone", "Shipped"),
    ("decision", "Decisions"),
    ("bug", "Bugs fixed"),
    ("journey", "Investigations finished"),
)
EXPORT_FORMAT = "arcane-export"
EXPORT_VERSION = 1


def _entry_from_memory(m: dict[str, Any]) -> dict[str, Any]:
    # A decision is worth its reason; a milestone or bug fix is worth what happened.
    summary = (m.get("why") if m["category"] == "decision" else None) or m.get("what") or ""
    return {
        "kind": m["category"],
        "id": m["id"],
        "date": m["created_at"][:10],
        "title": m["title"],
        "summary": summary,
        "tags": m.get("tags") or [],
    }


def build_report(
    container: ServiceContainer,
    since: date,
    until: date,
    *,
    org: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Collect report entries created from *since* to *until*, both days included."""
    start, end = since.isoformat(), (until + timedelta(days=1)).isoformat()
    memories = container.memory_repo.list_created_between(
        start, end, categories=REPORT_CATEGORIES, org=org, project=project
    )
    project_orgs = container.memory_repo.project_orgs()
    journeys = [
        j
        for j in container.journey_repo.list_completed_between(start, end)
        if (org is None or project_orgs.get(j["project"]) == org) and (project is None or j["project"] == project)
    ]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for m in memories:
        groups[(m["org"] or "(none)", m["project"] or "(no project)")].append(_entry_from_memory(m))
    for j in journeys:
        key = (project_orgs.get(j["project"], "(none)"), j["project"] or "(no project)")
        groups[key].append(
            {
                "kind": "journey",
                "id": j["id"],
                "date": (j["completed_at"] or "")[:10],
                "title": j["title"],
                "summary": j.get("summary") or "",
                "tags": [],
            }
        )

    totals = {kind: 0 for kind, _ in SECTIONS}
    projects = []
    for (group_org, group_project), entries in sorted(groups.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        for entry in entries:
            totals[entry["kind"]] += 1
        projects.append({"org": group_org, "project": group_project, "entries": entries})

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "org": org,
        "project": project,
        "totals": totals,
        "projects": projects,
    }


def _one_line(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report as markdown: org, then project, then one section per kind."""
    totals = report["totals"]
    scope = " · ".join(x for x in (report["org"], report["project"]) if x)
    lines = [
        f"# Work report: {report['since']} to {report['until']}" + (f" ({scope})" if scope else ""),
        "",
        f"{totals['milestone']} shipped · {totals['decision']} decisions · {totals['bug']} bugs fixed · "
        f"{totals['journey']} investigations finished",
    ]
    if not report["projects"]:
        lines += ["", "Nothing recorded in this period."]
    current_org = None
    for group in report["projects"]:
        if group["org"] != current_org:
            current_org = group["org"]
            lines += ["", f"## {current_org}"]
        lines += ["", f"### {group['project']}"]
        for kind, heading in SECTIONS:
            entries = [e for e in group["entries"] if e["kind"] == kind]
            if not entries:
                continue
            lines += ["", f"**{heading}**", ""]
            for e in entries:
                summary = _one_line(e["summary"])
                lines.append(f"- {e['date']} **{e['title']}**" + (f" — {summary}" if summary else ""))
    return "\n".join(lines) + "\n"


def export_org(container: ServiceContainer, org: str) -> dict[str, Any]:
    """Everything *org* owns: its memories (with details), and the journeys and artifacts of its projects."""
    memories = container.memory_repo.list_for_export(org)
    project_orgs = container.memory_repo.project_orgs()
    projects = sorted(p for p, o in project_orgs.items() if o == org)
    journeys = container.journey_repo.list_for_projects(projects)
    artifacts = container.artifact_repo.list_for_projects(projects)
    ids = {m["id"] for m in memories} | {j["id"] for j in journeys} | {a["id"] for a in artifacts}
    relationships = container.relationship_repo.list_touching(ids)
    for record in (*memories, *journeys, *artifacts):
        record.pop("rowid", None)
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "arcane_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "org": org,
        "projects": projects,
        "counts": {
            "memories": len(memories),
            "journeys": len(journeys),
            "artifacts": len(artifacts),
            "relationships": len(relationships),
        },
        "memories": memories,
        "journeys": journeys,
        "artifacts": artifacts,
        "relationships": relationships,
    }
