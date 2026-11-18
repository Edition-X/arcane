"""The decision log: a project's current decisions, newest first, and the ones they replaced.

Output is a pure function of the store, with no generation time and a fixed
order, so a regenerated file diffs only where a decision changed.
"""

from __future__ import annotations

from typing import Any

from arcane.services.container import ServiceContainer
from arcane.services.details_sections import DECISION_LOG_WORDS, find_sections

SECTION_LIMIT_CHARS = 1200
ID_PREFIX_CHARS = 8


def _cap(text: str, limit: int = SECTION_LIMIT_CHARS) -> str:
    """Cut *text* to about *limit* characters at a word boundary, ending with "…"; close a code fence the cut opened."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(None, 1)[0].rstrip() + "…"
    if sum(1 for line in cut.splitlines() if line.lstrip().startswith(("```", "~~~"))) % 2:
        cut += "\n```"
    return cut


def extract_options(details: str | None) -> list[dict[str, str]]:
    """The options, alternatives, trade-offs, considered and rejected sections of a details body.

    Args:
        details: The free-form details body, or ``None``.

    Returns:
        One ``{"label", "text"}`` dict per non-empty section, in order, each text capped at
        ``SECTION_LIMIT_CHARS`` with its line breaks kept. Empty when no section matches.
    """
    sections = find_sections(details, DECISION_LOG_WORDS, stop_at_blank=False)
    return [{"label": s.label, "text": _cap(s.text)} for s in sections if s.text]


def build_decision_log(container: ServiceContainer, *, org: str | None, project: str | None) -> dict[str, Any]:
    """Collect the current and replaced decisions of one project, or of one org.

    A decision counts as replaced when any memory supersedes it, even one that has since expired.
    Expired decisions are left out of both lists.

    Args:
        container: The service container holding the store.
        org: Only this org; ``None`` reads every org.
        project: Only this project; ``None`` reads every project of *org*.

    Returns:
        ``{"org", "project", "decisions", "replaced"}``, both lists newest first. A current decision has
        ``id``, ``date``, ``title``, ``project``, ``what``, ``why`` and ``options``; a replaced one has
        the first four and ``replaced_by`` (``id``, ``title``, ``date``).
    """
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
    """The first ``ID_PREFIX_CHARS`` characters of a memory id."""
    return memory_id[:ID_PREFIX_CHARS]


def _entry_blocks(d: dict[str, Any], where: str) -> list[str]:
    """The Markdown blocks of one current decision, without surrounding blank lines."""
    blocks = [f"### {d['date']} · {d['title']} (`{_short(d['id'])}`){where}"]
    if d["what"]:
        blocks.append(f"**What:** {d['what']}")
    if d["why"]:
        blocks.append(f"**Why:** {d['why']}")
    for option in d["options"]:
        quoted = "\n".join(f"> {line}".rstrip() for line in option["text"].splitlines())
        blocks += [f"**{option['label']}**", quoted]
    return blocks


def render_markdown(log: dict[str, Any]) -> str:
    """Render a decision log as Markdown: current decisions newest first, then the replaced ones.

    Args:
        log: The result of ``build_decision_log``.

    Returns:
        The document, ending in one newline. Entries show their project when the log spans a whole org.
    """
    scope = "/".join(x for x in (log["org"], log["project"]) if x)
    org_wide = log["project"] is None

    def where(d: dict[str, Any]) -> str:
        return f" · {d['project']}" if org_wide and d["project"] else ""

    blocks = [
        f"# Decision log: {scope}" if scope else "# Decision log",
        f"{len(log['decisions'])} current · {len(log['replaced'])} replaced",
        "## Decisions",
    ]
    if not log["decisions"]:
        blocks.append("No current decisions.")
    for d in log["decisions"]:
        blocks += _entry_blocks(d, where(d))
    blocks.append("## Replaced")
    if not log["replaced"]:
        blocks.append("Nothing replaced.")
    else:
        # One list: its items sit on consecutive lines, so join them into a single block.
        blocks.append(
            "\n".join(
                f"- {d['date']} · {d['title']} (`{_short(d['id'])}`){where(d)} — replaced by "
                f"`{_short(d['replaced_by']['id'])}` {d['replaced_by']['title']} ({d['replaced_by']['date']})"
                for d in log["replaced"]
            )
        )
    return "\n\n".join(blocks) + "\n"
