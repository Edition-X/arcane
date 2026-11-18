"""Calendar-date parsing shared by the domain and the clock."""

from __future__ import annotations

import re
from datetime import date

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_iso_date(value: str, name: str = "date") -> str:
    """*value* if it is a real ``YYYY-MM-DD`` date, else a ``ValueError`` naming *name*."""
    text = value.strip()
    try:
        if not _ISO_DATE.fullmatch(text):
            raise ValueError
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name} must be a real date as YYYY-MM-DD, got '{value}'") from None
    return text
