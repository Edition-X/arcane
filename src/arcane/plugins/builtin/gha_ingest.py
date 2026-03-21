"""GitHub Actions ingestion plugin — imports CI runs as artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class GHAIngestionPlugin:
    name = "github_actions"

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        return []

    def supports_incremental(self) -> bool:
        return True
