"""Three-layer secret redaction pipeline."""

from __future__ import annotations

import re

# Layer 2: Exact token patterns — entire match is redacted.
# Compiled once at module level for performance.
_EXACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk_live_[a-zA-Z0-9]+"),
    re.compile(r"sk_test_[a-zA-Z0-9]+"),
    re.compile(r"ghp_[a-zA-Z0-9]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),
    re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+"),
]

# Layer 3: Key=value patterns — key name is preserved, only value is redacted.
# Uses a capturing group so "password = [REDACTED]" reads naturally.
# Value terminates at whitespace, quotes, or common delimiters — never greedy.
_VALUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(password\s*[:=]\s*)[\"']?[^\s\"'<>;,]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(secret\s*[:=]\s*)[\"']?[^\s\"'<>;,]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(api[_-]?key\s*[:=]\s*)[\"']?[^\s\"'<>;,]+", re.IGNORECASE), r"\1[REDACTED]"),
]

_REDACTED_TAG_PATTERN: re.Pattern = re.compile(r"<redacted>.*?</redacted>", re.DOTALL)


def redact(text: str, extra_patterns: list[str] | None = None) -> str:
    """Redact sensitive information using three-layer approach.

    Layer 1 — explicit ``<redacted>…</redacted>`` tags.
    Layer 2 — well-known token patterns (Stripe, GitHub, AWS, Slack, JWT, …).
    Layer 3 — key=value patterns (password, secret, api_key); key is kept.
    Layer 4 — custom patterns from ``.memoryignore`` (user-defined regexes).
    """
    # Layer 1: strip explicit <redacted> tags
    prev = None
    while prev != text:
        prev = text
        text = _REDACTED_TAG_PATTERN.sub("[REDACTED]", text)
    # Remove any unclosed/unmatched tags left over
    text = text.replace("<redacted>", "").replace("</redacted>", "")

    # Layer 2: exact token patterns
    for pattern in _EXACT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    # Layer 3: key=value patterns (preserve key, redact value only)
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)

    # Layer 4: custom user patterns (compiled on-the-fly; skip malformed ones)
    for raw in extra_patterns or []:
        try:
            text = re.sub(raw, "[REDACTED]", text)
        except re.error:
            pass

    return text


def load_memoryignore(path: str) -> list[str]:
    """Load custom redaction patterns from a ``.memoryignore`` file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]
