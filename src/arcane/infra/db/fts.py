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


# Words too common to say what a search is about.
STOPWORDS = frozenset(
    "a about an and are as at be by can did do does for from go has have how i if in into is it its "
    "me my not of on or our should so that the this to was we were what when where which who why will "
    "with you".split()
)
MAX_KEY_TERMS = 8


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"*'


def key_terms(text: str) -> list[str]:
    """The distinct, lowercased words of *text* that carry meaning, in order."""
    seen: list[str] = []
    for raw in text.lower().split():
        term = raw.strip(".,;:!?()[]{}'\"`")
        if len(term) > 1 and term not in STOPWORDS and term not in seen:
            seen.append(term)
    return seen[:MAX_KEY_TERMS]


def key_terms_query(text: str) -> str | None:
    """An FTS5 expression matching memories that contain the key words of *text*.

    Up to three key words must all appear. With four or more, any one may be
    missing, so a long search is not judged unanswered over a single word.
    Returns ``None`` when *text* has no key words.
    """
    terms = key_terms(text)
    if not terms:
        return None
    if len(terms) <= 3:
        return " AND ".join(_quote(t) for t in terms)
    groups = [[t for j, t in enumerate(terms) if j != skip] for skip in range(len(terms))]
    return " OR ".join("(" + " AND ".join(_quote(t) for t in group) + ")" for group in groups)
