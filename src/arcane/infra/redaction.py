"""Secret redaction for explicit spans, known tokens and custom patterns."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Layer 2: Exact token patterns — entire match is redacted.
# Compiled once at module level for performance.
_EXACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk_live_[a-zA-Z0-9]+"),
    re.compile(r"sk_test_[a-zA-Z0-9]+"),
    re.compile(r"(?:sk-proj-|sk-svcacct-)[a-zA-Z0-9_-]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox(?:a|b|p|r|s)-[a-zA-Z0-9-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)?"),
]

# Layer 3: Credential assignments, including quoted JSON/YAML keys and values.
# Quoted values may contain spaces, delimiters and escaped quotes. An unclosed
# quoted value is redacted through the end of the input rather than leaked.
_VALUE_PATTERN = re.compile(
    r"""(["']?(?:password|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"""
    r"""["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?|[^\s"'<>;,}]+)""",
    re.IGNORECASE,
)

# Also recognise malformed markers (attributes, whitespace, missing final >).
# A nesting counter is needed: a non-greedy regex leaks the outer block's tail.
_REDACTED_TAG_PATTERN = re.compile(r"<\s*(/?)\s*redacted\b[^<>]*(?:>|(?=<)|$)", re.IGNORECASE)


def _redact_marked_spans(text: str) -> str:
    """Hide nested marked spans, failing closed for unmatched markers.

    An unclosed opening marker hides the rest of the input. An orphan closing
    marker hides everything before it because the opening boundary is unknown.
    """
    parts: list[str] = []
    depth = 0
    cursor = 0
    for marker in _REDACTED_TAG_PATTERN.finditer(text):
        if not marker.group(0).endswith(">"):
            # Do not let a later tag supply a malformed marker's missing >.
            # Its boundary is unknown, so discard the rest of the input.
            if depth == 0:
                if marker.group(1):
                    return "[REDACTED]"
                parts.extend((text[cursor : marker.start()], "[REDACTED]"))
            return "".join(parts)
        if not marker.group(1):
            if depth == 0:
                parts.extend((text[cursor : marker.start()], "[REDACTED]"))
            depth += 1
        elif depth:
            depth -= 1
        else:
            parts = ["[REDACTED]"]
        cursor = marker.end()
    if depth == 0:
        parts.append(text[cursor:])
    return "".join(parts)


def redact(text: str, extra_patterns: list[str] | None = None) -> str:
    """Redact sensitive information using four layers.

    Layer 1 — explicit ``<redacted>…</redacted>`` tags.
    Layer 2 — well-known token patterns (Stripe, GitHub, AWS, Slack, JWT, …).
    Layer 3 — key=value patterns (password, secret, api_key); key is kept.
    Layer 4 — custom patterns from ``.memoryignore`` (user-defined regexes).
    """
    # Layer 1: explicit markers, including nested and incomplete spans.
    text = _redact_marked_spans(text)

    # Layer 2: exact token patterns
    for pattern in _EXACT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    # Layer 3: key=value patterns (preserve key, redact value only)
    text = _VALUE_PATTERN.sub(r"\1[REDACTED]", text)

    # Layer 4: custom user patterns (compiled on-the-fly; skip malformed ones)
    for raw in extra_patterns or []:
        try:
            text = re.sub(raw, "[REDACTED]", text)
        except re.error:
            pass

    return text


def redact_values(value: Any, extra_patterns: list[str] | None = None) -> Any:
    """Recursively redact strings in JSON-like values before serialisation.

    Mapping keys are left alone. Every caller passes a dict whose keys are
    structure, not content — model dumps, column names, artifact ``raw_data``
    and insight ``metadata`` — so rewriting a key silently drops the field it
    names. A ``.memoryignore`` pattern matching ``journey_id`` once cost a save
    its journey link, and one matching ``title`` failed the save outright.
    """
    if isinstance(value, str):
        return redact(value, extra_patterns)
    if isinstance(value, list):
        return [redact_values(item, extra_patterns) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_values(item, extra_patterns) for item in value)
    if isinstance(value, dict):
        return {key: redact_values(item, extra_patterns) for key, item in value.items()}
    return value


def load_memoryignore(path: str) -> list[str]:
    """Load custom redaction patterns from a ``.memoryignore`` file.

    A pattern that is not a valid regex is dropped with a warning naming its
    line. Without one, a typo would leave whatever it was meant to catch
    stored in clear, and nothing would say so.
    """
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    patterns: list[str] = []
    for number, line in enumerate(lines, start=1):
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            logger.warning(
                "%s line %d: %r is not a valid regex (%s), so nothing it matches is redacted",
                path,
                number,
                pattern,
                exc,
            )
            continue
        patterns.append(pattern)
    return patterns
