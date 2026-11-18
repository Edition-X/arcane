"""Earlier decisions on the files a new decision names, with the options they weighed."""

from __future__ import annotations

import re
from typing import Any

from arcane.services.container import ServiceContainer

MAX_CURRENT = 5
MAX_SUPERSEDED = 3
EXCERPT_CHARS = 300

_OPTIONS_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*|\*\*)?(?:options(?:[ \t]+considered)?|rejected(?:[ \t]+options)?|alternatives)"
    r"(?:\*\*)?[ \t]*:?(?:\*\*)?[ \t]*(?P<rest>.*)$",
    re.IGNORECASE,
)
_ANY_HEADING = re.compile(r"^[ \t]*(?:#{1,6}[ \t]|\*\*[^*]+\*\*[ \t]*:?[ \t]*$|[A-Z][A-Za-z ]{1,30}:[ \t]*\S?)")


def same_file(a: str, b: str) -> bool:
    """Whether two stored paths name one file: equal, or one ends with "/" + the other."""
    a, b = a.strip(), b.strip()
    return bool(a and b) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


def shared_files(mine: list[str], theirs: list[str]) -> list[str]:
    """The paths in *theirs* that name a file in *mine*, in *theirs*' order."""
    return [t for t in theirs if any(same_file(m, t) for m in mine)]


def options_excerpt(details: str | None) -> str | None:
    """The options/rejected/alternatives part of a details body, cut to about 300 characters."""
    if not details:
        return None
    lines = details.splitlines()
    for i, line in enumerate(lines):
        match = _OPTIONS_HEADING.match(line)
        if not match:
            continue
        section = [match.group("rest").strip()]
        for nxt in lines[i + 1 :]:
            if _ANY_HEADING.match(nxt) and not _OPTIONS_HEADING.match(nxt):
                break
            section.append(nxt.strip())
        text = " ".join(part for part in section if part)
        if not text:
            return None
        return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1].rstrip() + "…"
    return None


class PriorDecisionsService:
    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def for_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Earlier decisions in *memory_id*'s project that share a file with it; best effort, [] on failure.

        Up to 5 current ones, then up to 3 replaced ones, newest first. Each has ``id``, ``title``,
        ``date``, ``shared_files``, ``superseded_by`` when replaced, and ``options`` when its details
        have an options section.
        """
        memory = self.c.memory_repo.get(memory_id)
        if not memory or memory.get("category") != "decision" or not memory.get("related_files"):
            return []
        mine: list[str] = memory["related_files"]
        phrases = sorted({_phrase(p) for p in mine if _phrase(p)})
        found = self.c.memory_repo.decision_candidates_for_files(phrases, memory["org"], memory["project"])
        hits = [(r, shared_files(mine, r["related_files"])) for r in found if r["id"] != memory_id]
        hits = [(r, files) for r, files in hits if files]
        replaced = self.c.relationship_repo.superseded_by([r["id"] for r, _ in hits])
        current = [h for h in hits if h[0]["id"] not in replaced][:MAX_CURRENT]
        old = [h for h in hits if h[0]["id"] in replaced][:MAX_SUPERSEDED]
        out: list[dict[str, Any]] = []
        for row, files in current + old:
            entry: dict[str, Any] = {
                "id": row["id"],
                "title": row["title"],
                "date": row["created_at"][:10],
                "shared_files": files,
            }
            if row["id"] in replaced:
                entry["superseded_by"] = replaced[row["id"]]["id"]
            options = options_excerpt((self.c.memory_repo.get_details(row["id"]) or {}).get("body"))
            if options:
                entry["options"] = options
            out.append(entry)
        return out


def _phrase(path: str) -> str:
    """The file name of *path* as FTS words, e.g. ``a/b/quux_handler.py`` -> ``quux handler py``."""
    return " ".join(re.findall(r"[^\W_]+", path.strip().rsplit("/", 1)[-1]))
