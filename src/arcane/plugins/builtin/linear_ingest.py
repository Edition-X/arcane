"""Linear ingestion plugin — imports tickets as artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class LinearIngestionPlugin:
    name = "linear"

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        return []

    def supports_incremental(self) -> bool:
        return True
