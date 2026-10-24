"""Insight repository — SQLite persistence for derived intelligence."""

from __future__ import annotations

import json
from typing import Any

from arcane.infra.db.connection import Database
from arcane.infra.db.ids import resolve_unique_id
from arcane.infra.redaction import redact_values


class InsightRepository:
    """CRUD operations for the insights table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, insight: dict[str, Any]) -> None:
        insight = redact_values(insight)
        assert isinstance(insight, dict)
        self.db.execute(
            """
            INSERT INTO insights (
                id, insight_type, title, body, severity, project, org, metadata, created_at, acknowledged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight["id"],
                insight["insight_type"],
                insight["title"],
                insight["body"],
                insight.get("severity", "info"),
                insight["project"],
                insight.get("org", ""),
                json.dumps(insight.get("metadata", {})),
                insight["created_at"],
                0,
            ),
        )
        self.db.commit()

    def acknowledge(self, insight_id: str, *, org: str | None = None, project: str | None = None) -> bool:
        full_id = resolve_unique_id(self.db, "insights", insight_id)
        if full_id is None:
            return False
        row = self.db.fetchone("SELECT * FROM insights WHERE id = ?", (full_id,))
        if (
            row is None
            or (org is not None and row["org"] != org)
            or (project is not None and row["project"] != project)
        ):
            return False
        self.db.execute("UPDATE insights SET acknowledged = 1 WHERE id = ?", (full_id,))
        self.db.commit()
        return True

    def list_all(
        self,
        project: str | None = None,
        unacknowledged_only: bool = False,
        limit: int = 20,
        org: str | None = None,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if org is not None:
            where_clauses.append("org = ?")
            params.append(org)
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

    def count(self, project: str | None = None, org: str | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("project", project), ("org", org)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        row = self.db.fetchone(f"SELECT COUNT(*) AS cnt FROM insights {where}", params)
        return row["cnt"] if row else 0
