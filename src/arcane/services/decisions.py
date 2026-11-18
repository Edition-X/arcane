"""The decision log: a project's current decisions, newest first, and the ones they replaced.

Output is a pure function of the store, with no generation time and a fixed
order, so a regenerated file diffs only where a decision changed.
"""

from __future__ import annotations

import re
from typing import Any

from arcane.services.container import ServiceContainer

SECTION_LIMIT = 1200
ID_PREFIX = 8

# A details section is kept when its heading or label names one of these.
_KEPT = re.compile(r"\b(options?|alternatives?|trade-?offs?|considered|rejected)\b", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s+(?P<label>.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")
_LABEL = re.compile(r"^\W{0,2}(?P<label>[A-Z][\w /&-]{0,40}?)\W{0,2}:(?:\s+(?P<rest>.*))?$")


def _split_sections(body: str) -> list[tuple[str, list[str]]]:
    """Cut *body* at markdown headings and at capitalised ``Label:`` lines."""
    sections: list[tuple[str, list[str]]] = []
    for line in body.splitlines():
        stripped = line.strip()
        heading = _HEADING.match(stripped)
        # A list item ("- Pros: ...", "1. Option A: ...") belongs to its section; it never opens one.
        label = None if heading or _LIST_ITEM.match(stripped) else _LABEL.match(stripped)
        if heading:
            sections.append((heading["label"].strip("*_ "), []))
        elif label:
            sections.append((label["label"].strip("*_ "), [label["rest"]] if label["rest"] else []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def _cap(text: str, limit: int = SECTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(None, 1)[0].rstrip() + "…"


def extract_options(details: str | None) -> list[dict[str, str]]:
    """The options, alternatives, trade-offs, considered and rejected sections of *details*, each capped."""
    if not details:
        return []
    found = []
    for label, lines in _split_sections(details):
        text = "\n".join(lines).strip()
        if text and _KEPT.search(label):
            found.append({"label": label, "text": _cap(text)})
    return found


def build_decision_log(container: ServiceContainer, *, org: str | None, project: str | None) -> dict[str, Any]:
    """Current and replaced decisions of *project* (or of the whole *org* when *project* is ``None``)."""
    rows = container.memory_repo.list_decisions(org=org, project=project)
    replaced_by = container.relationship_repo.superseded_by([r["id"] for r in rows])
    current, replaced = [], []
    for row in rows:
        entry = {
            "id": row["id"],
            "date": row["created_at"][:10],
            "title": row["title"],
            "project": row["project"],
        }
        if row["id"] in replaced_by:
            replaced.append({**entry, "replaced_by": replaced_by[row["id"]]})
        else:
            current.append(
                {
                    **entry,
                    "what": (row["what"] or "").strip(),
                    "why": (row["why"] or "").strip(),
                    "options": extract_options(row.get("details")),
                }
            )
    return {"org": org, "project": project, "decisions": current, "replaced": replaced}


def _short(memory_id: str) -> str:
    return memory_id[:ID_PREFIX]


def render_markdown(log: dict[str, Any]) -> str:
    """Render the log as markdown: current decisions newest first, then the replaced ones."""
    scope = "/".join(x for x in (log["org"], log["project"]) if x)
    org_wide = log["project"] is None
    lines = [
        f"# Decision log: {scope}" if scope else "# Decision log",
        "",
        f"{len(log['decisions'])} current · {len(log['replaced'])} replaced",
        "",
        "## Decisions",
    ]
    if not log["decisions"]:
        lines += ["", "No current decisions."]
    for d in log["decisions"]:
        where = f" · {d['project']}" if org_wide and d["project"] else ""
        lines += ["", f"### {d['date']} · {d['title']} (`{_short(d['id'])}`){where}", ""]
        if d["what"]:
            lines += [f"**What:** {d['what']}", ""]
        if d["why"]:
            lines += [f"**Why:** {d['why']}", ""]
        for option in d["options"]:
            lines += [f"**{option['label']}**", ""]
            lines += [f"> {line}".rstrip() for line in option["text"].splitlines()]
            lines.append("")
        lines.pop()  # each entry ends without a blank line; the next heading adds one
    lines += ["", "## Replaced"]
    if not log["replaced"]:
        lines += ["", "Nothing replaced."]
    else:
        lines.append("")
    for d in log["replaced"]:
        by = d["replaced_by"]
        where = f" · {d['project']}" if org_wide and d["project"] else ""
        lines.append(
            f"- {d['date']} · {d['title']} (`{_short(d['id'])}`){where} — replaced by `{_short(by['id'])}` "
            f"{by['title']} ({by['date']})"
        )
    return "\n".join(lines) + "\n"
