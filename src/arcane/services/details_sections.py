"""Find named sections, such as the options considered, in a memory's free-form details body.

One grammar serves ``prior_decisions`` (the options excerpt shown on save) and the
decision log, so both read the same details the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# The words that open an options section; a heading may carry more after them ("Options considered for
# the cache"). Plural "options" only, so a line such as "Option A: keep tags" is a list entry, not a heading.
OPTIONS_WORDS = r"(?:options(?:[ \t]+considered)?|rejected(?:[ \t]+options)?|alternatives)"
# The decision log keeps the trade-offs and "considered" sections too.
DECISION_LOG_WORDS = r"(?:options(?:[ \t]+considered)?|rejected(?:[ \t]+options)?|alternatives|trade-?offs?|considered)"

# What ends a section, besides a blank line after it: a markdown heading, a bold-only line, or a known
# section name with a colon, bold or not. Not any "Name: reason" line, which is how options themselves
# are often listed.
_NEXT_SECTION = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]|\*\*[^*]+\*\*[ \t]*:?[ \t]*$"
    r"|(?:\*\*)?(?:context|decision|tradeoffs?|trade-offs?|follow-?ups?|why|consequences|outcome|notes?)"
    r"[ \t]*(?:\*\*)?[ \t]*:)",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")


@dataclass(frozen=True)
class DetailsSection:
    """One section of a details body: its heading text and its lines, heading line excluded."""

    label: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        """The section's lines with line breaks kept, trimmed at both ends."""
        return "\n".join(self.lines).strip()


@lru_cache(maxsize=None)
def _heading(words: str) -> re.Pattern[str]:
    """The heading that opens a section named by *words*.

    A markdown heading ("## Alternatives considered"), a bold one ("**Rejected**", "**Options
    considered:**" or "**Options considered**:"), a bare "Options considered" line, or a plain line
    whose words end in a colon within 80 characters ("Options considered for the cache:"). Prose
    such as "Options were limited." has no colon, so it is not taken for one.
    """
    return re.compile(
        rf"^[ \t]*(?:#{{1,6}}[ \t]*{words}\b[^:\n]*:?"
        rf"|\*\*{words}\b[^*\n]*\*\*[ \t]*:?|\*\*{words}\b[^*:\n]*:\*\*"
        rf"|{words}\b[^:\n]{{0,80}}:|{words}[ \t]*$)"
        r"[ \t]*(?P<rest>.*)$",
        re.IGNORECASE,
    )


def find_sections(details: str | None, words: str, *, stop_at_blank: bool) -> list[DetailsSection]:
    """The sections of *details* whose heading starts with one of *words*, in order.

    A section runs from its heading to the next markdown heading, bold-only line, known section name
    (Context, Decision, Tradeoffs, Follow-up, Why, ...) or heading of another wanted section. List items
    and "Name: reason" lines stay inside it. Nothing inside a code fence starts or ends a section.

    Args:
        details: The free-form details body; ``None`` or empty gives no sections.
        words: A regex fragment for the heading words, such as ``OPTIONS_WORDS``; matched ignoring case.
        stop_at_blank: End a section at the first blank line after its content.

    Returns:
        The wanted sections, each with its label and lines; a section with no text is still returned.
    """
    if not details:
        return []
    heading = _heading(words)
    lines = details.splitlines()
    found: list[DetailsSection] = []
    i = 0
    fenced = False
    while i < len(lines):
        if _FENCE.match(lines[i]):
            fenced = not fenced
        match = None if fenced else heading.match(lines[i])
        if not match:
            i += 1
            continue
        label = lines[i][: match.start("rest")].strip().lstrip("#").strip("*: \t")
        body = [match.group("rest").strip()] if match.group("rest").strip() else []
        i += 1
        in_fence = False
        while i < len(lines):
            line = lines[i]
            if _FENCE.match(line):
                in_fence = not in_fence
            elif not in_fence:
                if stop_at_blank and not line.strip() and any(part.strip() for part in body):
                    break
                if _NEXT_SECTION.match(line) or heading.match(line):
                    break
            body.append(line.rstrip())
            i += 1
        found.append(DetailsSection(label=label, lines=tuple(body)))
    return found
