"""Domain enumerations for Arcane."""

from enum import StrEnum


class Category(StrEnum):
    DECISION = "decision"
    PATTERN = "pattern"
    BUG = "bug"
    CONTEXT = "context"
    LEARNING = "learning"
    POC = "poc"
    MILESTONE = "milestone"


CATEGORY_HEADINGS: dict[str, str] = {
    Category.DECISION: "Decisions",
    Category.PATTERN: "Patterns",
    Category.BUG: "Bugs Fixed",
    Category.CONTEXT: "Context",
    Category.LEARNING: "Learnings",
    Category.POC: "Proof of Concepts",
    Category.MILESTONE: "Milestones",
}


class ArtifactType(StrEnum):
    COMMIT = "commit"
    PR = "pr"
    CI_RUN = "ci_run"
    LINEAR_TICKET = "linear_ticket"
    AGENT_SESSION = "agent_session"
    ADR = "adr"
    BLOG_POST = "blog_post"


class RelationType(StrEnum):
    LED_TO = "led_to"
    INFORMED_BY = "informed_by"
    RESULTED_IN = "resulted_in"
    PART_OF = "part_of"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"


class JourneyStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
