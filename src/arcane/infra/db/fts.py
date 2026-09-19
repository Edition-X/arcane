"""FTS5 query construction shared by the repositories."""

from __future__ import annotations


def prefix_or_query(text: str) -> str | None:
    """Build an FTS5 ``MATCH`` expression that ORs a prefix query per term.

    Every term is quoted as an FTS5 string, with embedded double quotes
    doubled, so user text such as ``say "hi`` can never break the query
    syntax. Returns ``None`` when *text* has no terms.
    """
    terms = text.split()
    if not terms:
        return None
    return " OR ".join('"' + term.replace('"', '""') + '"*' for term in terms)
