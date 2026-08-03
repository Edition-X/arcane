"""Journey repository — SQLite persistence for decision journeys."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from arcane.infra.db.connection import Database
from arcane.infra.db.ids import resolve_unique_id
from arcane.infra.redaction import redact, redact_values


class JourneyRepository:
    """CRUD operations for the journeys table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, journey: dict[str, Any]) -> int:
        journey = redact_values(journey)
        assert isinstance(journey, dict)
        cursor = self.db.execute(
            """
            INSERT INTO journeys (
                id, title, project, status, started_at, completed_at,
                summary, linear_issue_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                journey["id"],
                journey["title"],
                journey["project"],
                journey.get("status", "active"),
                journey["started_at"],
                journey.get("completed_at"),
                journey.get("summary"),
                journey.get("linear_issue_id"),
                journey["created_at"],
                journey["updated_at"],
            ),
        )
        self.db.commit()
        return cursor.lastrowid  # type: ignore[no-any-return]

    def get(self, journey_id: str) -> dict[str, Any] | None:
        full_id = resolve_unique_id(self.db, "journeys", journey_id)
        if full_id is None:
            return None
        return self.db.fetchone("SELECT * FROM journeys WHERE id = ?", (full_id,))

    def update(
        self,
        journey_id: str,
        *,
        event_type: str | None = None,
        event_summary: str | None = None,
        **fields: Any,
    ) -> bool:
        full_id = resolve_unique_id(self.db, "journeys", journey_id)
        if full_id is None:
            return False
        fields = redact_values(fields)
        assert isinstance(fields, dict)
        event_summary = redact(event_summary) if event_summary is not None else None
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        if event_type is None and "summary" in fields:
            event_type = "updated"
            event_summary = fields["summary"]

        sets = [f"{k} = ?" for k in fields]
        params = list(fields.values()) + [full_id]
        self.db.execute(f"UPDATE journeys SET {', '.join(sets)} WHERE id = ?", params)
        if event_type:
            self._insert_event(full_id, event_type, event_summary)
        self.db.commit()
        return True

    def complete(self, journey_id: str, summary: str | None = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {"status": "completed", "completed_at": now}
        if summary:
            fields["summary"] = summary
        return self.update(journey_id, event_type="completed", event_summary=summary, **fields)

    def abandon(self, journey_id: str, reason: str | None = None) -> bool:
        fields: dict[str, Any] = {"status": "abandoned"}
        summary = f"Abandoned: {reason}" if reason else None
        if summary:
            fields["summary"] = summary
        return self.update(journey_id, event_type="abandoned", event_summary=summary, **fields)

    def list_events(self, journey_id: str) -> list[dict[str, Any]]:
        full_id = resolve_unique_id(self.db, "journeys", journey_id)
        if full_id is None:
            return []
        return self.db.fetchall(
            "SELECT * FROM journey_events WHERE journey_id = ? ORDER BY created_at, rowid",
            (full_id,),
        )

    def list_all(
        self,
        project: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if project:
            where_clauses.append("project = ?")
            params.append(project)
        if status:
            where_clauses.append("status = ?")
            params.append(status)

        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        params.append(limit)

        return self.db.fetchall(
            f"SELECT * FROM journeys {where_clause} ORDER BY created_at DESC LIMIT ?",
            params,
        )

    def list_stale_active(self, days: int, project: str | None = None) -> list[dict[str, Any]]:
        """Active journeys whose ``started_at`` is more than *days* days ago."""
        where_clauses = ["status = 'active'", "(unixepoch('now') - unixepoch(started_at)) > ? * 86400"]
        params: list[Any] = [days]
        if project:
            where_clauses.append("project = ?")
            params.append(project)
        return self.db.fetchall(
            f"SELECT * FROM journeys WHERE {' AND '.join(where_clauses)} ORDER BY started_at",
            params,
        )

    def delete(self, journey_id: str) -> bool:
        """Delete a journey by exact ID or prefix. Relationships are the caller's job."""
        full_id = resolve_unique_id(self.db, "journeys", journey_id)
        if full_id is None:
            return False
        self.db.execute("DELETE FROM journey_events WHERE journey_id = ?", (full_id,))
        self.db.execute("DELETE FROM journeys WHERE id = ?", (full_id,))
        self.db.commit()
        return True

    def count(self, project: str | None = None) -> int:
        if project:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM journeys WHERE project = ?", (project,))
        else:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM journeys")
        return row["cnt"] if row else 0

    def _insert_event(self, journey_id: str, event_type: str, summary: str | None) -> None:
        self.db.execute(
            "INSERT INTO journey_events (id, journey_id, event_type, summary, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), journey_id, event_type, summary, datetime.now(timezone.utc).isoformat()),
        )
