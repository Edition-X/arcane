"""Plugin protocol definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IngestionPlugin(Protocol):
    """Pulls data from an external source into Arcane."""

    name: str

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]: ...

    def supports_incremental(self) -> bool: ...


@runtime_checkable
class IntelligencePlugin(Protocol):
    """Analyzes stored data and produces Insights."""

    name: str

    def analyze(self, project: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class ContentPlugin(Protocol):
    """Generates structured content from stored knowledge."""

    name: str

    def generate(self, context: dict[str, Any]) -> str: ...
