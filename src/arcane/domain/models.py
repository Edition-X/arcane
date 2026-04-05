"""Domain models for Arcane — Pydantic v2 models for all entities."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from arcane.domain.enums import (
    ArtifactType,
    Category,
    JourneyStatus,
    RelationType,
    Severity,
)


def _generate_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Memory (backward-compatible with EchoVault)
# ---------------------------------------------------------------------------


class RawMemoryInput(BaseModel):
    """Raw input for creating a memory before processing."""

    title: str = Field(max_length=60)
    what: str
    why: str | None = None
    impact: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    related_files: list[str] = Field(default_factory=list)
    details: str | None = None
    source: str | None = None
    journey_id: str | None = None

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        valid = {c.value for c in Category}
        if v not in valid:
            raise ValueError(
                f"Invalid category '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v


class Memory(BaseModel):
    """A memory record with all metadata."""

    id: str = Field(default_factory=_generate_id)
    title: str
    what: str
    why: str | None = None
    impact: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    project: str = ""
    source: str | None = None
    related_files: list[str] = Field(default_factory=list)
    file_path: str = ""
    section_anchor: str = ""
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    updated_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def from_raw(raw: RawMemoryInput, project: str, file_path: str = "") -> Memory:
        anchor = re.sub(r"[^a-z0-9]+", "-", raw.title.lower()).strip("-")
        now = _now_iso()
        return Memory(
            title=raw.title,
            what=raw.what,
            why=raw.why,
            impact=raw.impact,
            tags=raw.tags,
            category=raw.category,
            project=project,
            source=raw.source,
            related_files=raw.related_files,
            file_path=file_path,
            section_anchor=anchor,
            created_at=now,
            updated_at=now,
            metadata={"journey_id": raw.journey_id} if raw.journey_id else {},
        )


class MemoryDetail(BaseModel):
    """Full details/body content for a memory."""

    memory_id: str
    body: str


class SearchResult(BaseModel):
    """Search result with score and metadata."""

    id: str
    title: str
    what: str
    why: str | None = None
    impact: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    project: str = ""
    source: str | None = None
    score: float = 0.0
    has_details: bool = False
    file_path: str = ""
    created_at: str = ""


# ---------------------------------------------------------------------------
# Journey
# ---------------------------------------------------------------------------


class Journey(BaseModel):
    """A decision journey — the narrative arc from problem to solution."""

    id: str = Field(default_factory=_generate_id)
    title: str
    project: str = ""
    status: JourneyStatus = JourneyStatus.ACTIVE
    started_at: str = Field(default_factory=_now_iso)
    completed_at: str | None = None
    summary: str | None = None
    linear_issue_id: str | None = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class Artifact(BaseModel):
    """An external reference — commit, PR, CI run, ticket, etc."""

    id: str = Field(default_factory=_generate_id)
    artifact_type: ArtifactType
    external_id: str
    title: str
    url: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    project: str = ""
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------


class Relationship(BaseModel):
    """A directed edge connecting any two entities."""

    id: str = Field(default_factory=_generate_id)
    source_type: str  # "memory", "journey", "artifact"
    source_id: str
    target_type: str
    target_id: str
    relation: RelationType
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Insight
# ---------------------------------------------------------------------------


class Insight(BaseModel):
    """A derived intelligence finding."""

    id: str = Field(default_factory=_generate_id)
    insight_type: str
    title: str
    body: str
    severity: Severity = Severity.INFO
    project: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    acknowledged: bool = False
