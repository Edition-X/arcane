"""Three-layer secret redaction pipeline."""

from __future__ import annotations

import re

SENSITIVE_PATTERNS = [
    r"sk_live_[a-zA-Z0-9]+",
    r"sk_test_[a-zA-Z0-9]+",
    r"ghp_[a-zA-Z0-9]+",
    r"AKIA[0-9A-Z]{16}",
    r"xoxb-[a-zA-Z0-9-]+",
    r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
    r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+",
    r"password\s*[:=]\s*[\"']?.+",
    r"secret\s*[:=]\s*[\"']?.+",
    r"api[_-]?key\s*[:=]\s*[\"']?.+",
]

REDACTED_TAG_PATTERN = re.compile(r"<redacted>.*?</redacted>", re.DOTALL)


def redact(text: str, extra_patterns: list[str] | None = None) -> str:
    """Redact sensitive information using three-layer approach."""
    # Layer 1: Explicit <redacted> tags
    while True:
        prev_text = text
        text = REDACTED_TAG_PATTERN.sub("[REDACTED]", text)
        if prev_text == text:
            break

    text = text.replace("<redacted>", "").replace("</redacted>", "")

    # Layer 2 + 3: Automatic + custom patterns
    all_patterns = SENSITIVE_PATTERNS + (extra_patterns or [])
    for pattern in all_patterns:
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)

    return text


def load_memoryignore(path: str) -> list[str]:
    """Load custom redaction patterns from a .memoryignore file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]
