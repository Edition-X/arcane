"""Artifact repository — SQLite persistence for external references."""

from __future__ import annotations

import json
from typing import Any

from arcane.infra.db.connection import Database
from arcane.infra.redaction import redact_values


class ArtifactRepository:
    """CRUD operations for the artifacts table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, artifact: dict[str, Any]) -> int:
        artifact = redact_values(artifact)
        assert isinstance(artifact, dict)
        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO artifacts (
                id, artifact_type, external_id, title, url, raw_data, project, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["id"],
                artifact["artifact_type"],
                artifact["external_id"],
                artifact["title"],
                artifact.get("url"),
                json.dumps(artifact.get("raw_data", {})),
                artifact["project"],
                artifact["created_at"],
            ),
        )
        self.db.commit()
        return cursor.lastrowid  # type: ignore[no-any-return]

    def get_many(self, artifact_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch multiple artifacts by exact ID in a single query."""
        if not artifact_ids:
            return []
        placeholders = ",".join("?" for _ in artifact_ids)
        return self.db.fetchall(
            f"SELECT * FROM artifacts WHERE id IN ({placeholders})",
            artifact_ids,
        )

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        return self.db.fetchone("SELECT * FROM artifacts WHERE id LIKE ?", (artifact_id + "%",))

    def fts_search(
        self,
        query: str,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search artifact metadata and ingested raw content with FTS5."""
        terms = query.split()
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"*' for term in terms)
        clauses: list[str] = []
        params: list[Any] = [fts_query]
        if project:
            clauses.append("a.project = ?")
            params.append(project)
        if artifact_type:
            clauses.append("a.artifact_type = ?")
            params.append(artifact_type)
        where = " AND " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        return self.db.fetchall(
            f"""
            SELECT a.*, -fts.rank AS score
            FROM artifacts_fts fts
            JOIN artifacts a ON a.rowid = fts.rowid
            WHERE fts.artifacts_fts MATCH ?{where}
            ORDER BY fts.rank
            LIMIT ?
            """,
            params,
        )

    def find_by_external(self, artifact_type: str, external_id: str, project: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            "SELECT * FROM artifacts WHERE artifact_type = ? AND external_id = ? AND project = ?",
            (artifact_type, external_id, project),
        )

    def list_all(
        self,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if project:
            where_clauses.append("project = ?")
            params.append(project)
        if artifact_type:
            where_clauses.append("artifact_type = ?")
            params.append(artifact_type)

        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        params.append(limit)

        return self.db.fetchall(
            f"SELECT * FROM artifacts {where_clause} ORDER BY created_at DESC LIMIT ?",
            params,
        )

    def count(self, project: str | None = None) -> int:
        if project:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM artifacts WHERE project = ?", (project,))
        else:
            row = self.db.fetchone("SELECT COUNT(*) as cnt FROM artifacts")
        return row["cnt"] if row else 0
