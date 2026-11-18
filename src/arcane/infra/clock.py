"""Today's date, from one place so tests can fix it."""

from __future__ import annotations

import os
from datetime import date

from arcane.domain.dates import parse_iso_date

TODAY_ENV = "ARCANE_TODAY"


def today() -> date:
    """The local date, or the one in ``ARCANE_TODAY`` (``YYYY-MM-DD``) when that is set."""
    override = os.environ.get(TODAY_ENV, "").strip()
    if override:
        return date.fromisoformat(parse_iso_date(override, TODAY_ENV))
    return date.today()
