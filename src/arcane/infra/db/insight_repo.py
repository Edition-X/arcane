"""Insight repository — SQLite persistence for derived intelligence."""

from __future__ import annotations

import json
from typing import Any

from arcane.infra.db.connection import Database


class InsightRepository:
    """CRUD operations for the insights table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, insight: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO insights (
                id, insight_type, title, body, severity, project, metadata, created_at, acknowledged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight["id"],
                insight["insight_type"],
                insight["title"],
                insight["body"],
                insight.get("severity", "info"),
                insight["project"],
                json.dumps(insight.get("metadata", {})),
                insight["created_at"],
                0,
            ),
        )
        self.db.commit()

    def acknowledge(self, insight_id: str) -> bool:
        row = self.db.fetchone("SELECT id FROM insights WHERE id LIKE ?", (insight_id + "%",))
        if not row:
            return False
        self.db.execute("UPDATE insights SET acknowledged = 1 WHERE id = ?", (row["id"],))
        self.db.commit()
        return True

    def list_all(
        self,
        project: str | None = None,
        unacknowledged_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if project:
            where_clauses.append("project = ?")
            params.append(project)
        if unacknowledged_only:
            where_clauses.append("acknowledged = 0")

        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        params.append(limit)

        return self.db.fetchall(
            f"SELECT * FROM insights {where_clause} ORDER BY created_at DESC LIMIT ?",
            params,
        )

    def count(self, project: str | None = None) -> int:
        if project:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM insights WHERE project = ?", (project,))
        else:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM insights")
        return row["cnt"] if row else 0
