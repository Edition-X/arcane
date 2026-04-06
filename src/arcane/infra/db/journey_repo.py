"""Journey repository — SQLite persistence for decision journeys."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from arcane.infra.db.connection import Database


class JourneyRepository:
    """CRUD operations for the journeys table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, journey: dict[str, Any]) -> int:
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
        return cursor.lastrowid  # type: ignore[return-value]

    def get(self, journey_id: str) -> dict[str, Any] | None:
        return self.db.fetchone("SELECT * FROM journeys WHERE id LIKE ?", (journey_id + "%",))

    def update(self, journey_id: str, **fields: Any) -> bool:
        row = self.db.fetchone("SELECT id FROM journeys WHERE id LIKE ?", (journey_id + "%",))
        if not row:
            return False

        full_id = row["id"]
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()

        sets = [f"{k} = ?" for k in fields]
        params = list(fields.values()) + [full_id]
        self.db.execute(f"UPDATE journeys SET {', '.join(sets)} WHERE id = ?", params)
        self.db.commit()
        return True

    def complete(self, journey_id: str, summary: str | None = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {"status": "completed", "completed_at": now}
        if summary:
            fields["summary"] = summary
        return self.update(journey_id, **fields)

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

    def count(self, project: str | None = None) -> int:
        if project:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM journeys WHERE project = ?", (project,))
        else:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM journeys")
        return row["cnt"] if row else 0
