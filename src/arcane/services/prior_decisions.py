"""Earlier decisions on the files a new decision names, with the options they weighed."""

from __future__ import annotations

import os
from typing import Any

from arcane.services.container import ServiceContainer
from arcane.services.details_sections import OPTIONS_WORDS, find_sections
from arcane.services.why import path_matches

MAX_CURRENT = 5
MAX_SUPERSEDED = 3
EXCERPT_CHARS = 300
# Only decisions are weighed against a new decision.
PRIOR_CATEGORIES = ("decision",)


def shared_files(mine: list[str], theirs: list[str]) -> list[str]:
    """The paths in *theirs* that name a file in *mine*, in *theirs*' order."""
    # path_matches is one-way (stored ends with target); a save may name either form, so try both.
    return [path for path in theirs if any(path_matches(path, m) or path_matches(m, path) for m in mine)]


def options_excerpt(details: str | None) -> str | None:
    """The options/rejected/alternatives part of a details body, cut to ``EXCERPT_CHARS``."""
    for section in find_sections(details, OPTIONS_WORDS, stop_at_blank=True):
        text = " ".join(part.strip() for part in section.lines if part.strip())
        if text:
            return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1].rstrip() + "…"
    return None


class PriorDecisionsService:
    """Finds the earlier decisions on the files a newly saved decision names."""

    def __init__(self, container: ServiceContainer) -> None:
        self.c = container

    def for_memory(self, memory_id: str) -> list[dict[str, Any]]:
        """Earlier decisions in *memory_id*'s project that share a file with it.

        Up to ``MAX_CURRENT`` current ones, then up to ``MAX_SUPERSEDED`` replaced ones, each
        group newest first. Each has ``id``, ``title``, ``date``, ``shared_files``,
        ``superseded_by`` when replaced, and ``options`` when its details have an options
        section. Candidates come from the query ``arcane why`` uses; ``shared_files`` keeps
        the real matches.
        """
        memory = self.c.memory_repo.get(memory_id)
        if not memory or memory.get("category") != "decision" or not memory.get("related_files"):
            return []
        mine: list[str] = memory["related_files"]
        found = self.c.memory_repo.why_candidates_for_files(
            sorted({os.path.basename(p) for p in mine}), PRIOR_CATEGORIES, memory["org"], memory["project"]
        )
        found.sort(key=lambda row: row["created_at"], reverse=True)
        # What this memory replaces is its own history, not a prior decision to weigh.
        skip = {memory_id} | {r["id"] for r in self.c.relationship_repo.supersedes(memory_id)}
        hits = [(row, shared_files(mine, row["related_files"])) for row in found if row["id"] not in skip]
        hits = [(row, files) for row, files in hits if files]
        replaced = self.c.relationship_repo.superseded_by([row["id"] for row, _ in hits])
        current = [(row, files) for row, files in hits if row["id"] not in replaced][:MAX_CURRENT]
        old = [(row, files) for row, files in hits if row["id"] in replaced][:MAX_SUPERSEDED]
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
