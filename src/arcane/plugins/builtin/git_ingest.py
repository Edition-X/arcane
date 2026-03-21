"""Git ingestion plugin — imports commits and branches as artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class GitIngestionPlugin:
    name = "git"

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        # Phase 2 implementation
        return []

    def supports_incremental(self) -> bool:
        return True
