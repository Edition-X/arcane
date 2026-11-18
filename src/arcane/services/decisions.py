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


def _close_open_fence(text: str) -> str:
    """Close a code fence *text* leaves open, with the marker it opened with, so it cannot swallow what follows."""
    opener: str | None = None
    for line in text.splitlines():
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            opener = None if opener == marker else (opener or marker)
    return text if opener is None else f"{text}\n{opener}"


def _cap(text: str, limit: int = SECTION_LIMIT_CHARS) -> str:
    """Cut *text* to about *limit* characters at a word boundary, ending with "…"."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(None, 1)[0].rstrip() + "…"


def extract_options(details: str | None) -> list[dict[str, str]]:
    """The options, alternatives, trade-offs, considered and rejected sections of a details body.

    Args:
        details: The free-form details body, or ``None``.

    Returns:
        One ``{"label", "text"}`` dict per non-empty section, in order, each text capped at
        ``SECTION_LIMIT_CHARS`` with its line breaks kept and any code fence closed. Empty when no
        section matches. A section ends at a blank line followed by prose, so later paragraphs stay out.
    """
    sections = find_sections(details, DECISION_LOG_WORDS, blank_ends="prose")
    return [{"label": s.label, "text": _close_open_fence(_cap(s.text))} for s in sections if s.text]


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


def _entry_blocks(decision: dict[str, Any], where: str) -> list[str]:
    """The Markdown blocks of one current decision, without surrounding blank lines."""
    blocks = [f"### {decision['date']} · {decision['title']} (`{_short(decision['id'])}`){where}"]
    if decision["what"]:
        blocks.append(f"**What:** {decision['what']}")
    if decision["why"]:
        blocks.append(f"**Why:** {decision['why']}")
    for option in decision["options"]:
        quoted = "\n".join(f"> {line}".rstrip() for line in option["text"].splitlines())
        blocks += [f"**{option['label']}**", quoted]
    return blocks


def render_markdown(log: dict[str, Any]) -> str:
    """Render a decision log as Markdown: current decisions newest first, then the replaced ones.

    Args:
        log: The result of ``build_decision_log``.

    Returns:
        The document, ending in one newline. Entries show their project when the log spans a whole
        org; the heading says "all orgs" when it spans every org that has the project.
    """
    scope = "/".join(x for x in (log["org"], log["project"]) if x)
    if log["org"] is None and log["project"]:
        scope += " (all orgs)"
    org_wide = log["project"] is None

    def where(decision: dict[str, Any]) -> str:
        """The " · project" suffix of an entry, only when the log covers a whole org."""
        return f" · {decision['project']}" if org_wide and decision["project"] else ""

    blocks = [
        f"# Decision log: {scope}" if scope else "# Decision log",
        f"{len(log['decisions'])} current · {len(log['replaced'])} replaced",
        "## Decisions",
    ]
    if not log["decisions"]:
        blocks.append("No current decisions.")
    for decision in log["decisions"]:
        blocks += _entry_blocks(decision, where(decision))
    blocks.append("## Replaced")
    if not log["replaced"]:
        blocks.append("Nothing replaced.")
    else:
        # One list: its items sit on consecutive lines, so join them into a single block.
        blocks.append(
            "\n".join(
                f"- {old['date']} · {old['title']} (`{_short(old['id'])}`){where(old)} — replaced by "
                f"`{_short(old['replaced_by']['id'])}` {old['replaced_by']['title']} ({old['replaced_by']['date']})"
                for old in log["replaced"]
            )
        )
    return "\n\n".join(blocks) + "\n"
