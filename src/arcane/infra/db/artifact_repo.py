"""Artifact repository — SQLite persistence for external references."""

from __future__ import annotations

import json
from typing import Any

from arcane.infra.db.connection import Database
from arcane.infra.db.fts import prefix_or_query
from arcane.infra.db.ids import resolve_unique_id
from arcane.infra.redaction import redact_values


class ArtifactRepository:
    """CRUD operations for the artifacts table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _process_row(row: dict[str, Any]) -> dict[str, Any]:
        """Deserialize persisted raw data at the repository boundary."""
        raw_data = row.get("raw_data")
        if isinstance(raw_data, str):
            try:
                row["raw_data"] = json.loads(raw_data) if raw_data else {}
            except json.JSONDecodeError:
                # Preserve malformed legacy content for inspection/export.
                pass
        elif raw_data is None:
            row["raw_data"] = {}
        return row

    def insert(self, artifact: dict[str, Any]) -> int:
        artifact = redact_values(artifact)
        assert isinstance(artifact, dict)
        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO artifacts (
                id, artifact_type, external_id, title, url, raw_data, project, org, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["id"],
                artifact["artifact_type"],
                artifact["external_id"],
                artifact["title"],
                artifact.get("url"),
                json.dumps(artifact.get("raw_data", {})),
                artifact["project"],
                artifact.get("org", ""),
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
        return [
            self._process_row(row)
            for row in self.db.fetchall(
                f"SELECT * FROM artifacts WHERE id IN ({placeholders})",
                artifact_ids,
            )
        ]

    def get(self, artifact_id: str, *, org: str | None = None, project: str | None = None) -> dict[str, Any] | None:
        full_id = resolve_unique_id(self.db, "artifacts", artifact_id)
        if full_id is None:
            return None
        row = self.db.fetchone("SELECT * FROM artifacts WHERE id = ?", (full_id,))
        if (
            row is None
            or (org is not None and row["org"] != org)
            or (project is not None and row["project"] != project)
        ):
            return None
        return self._process_row(row)

    def fts_search(
        self,
        query: str,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 10,
        org: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search artifact metadata and ingested raw content with FTS5."""
        fts_query = prefix_or_query(query)
        if fts_query is None:
            return []
        clauses: list[str] = []
        params: list[Any] = [fts_query]
        if org is not None:
            clauses.append("a.org = ?")
            params.append(org)
        if project:
            clauses.append("a.project = ?")
            params.append(project)
        if artifact_type:
            clauses.append("a.artifact_type = ?")
            params.append(artifact_type)
        where = " AND " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        return [
            self._process_row(row)
            for row in self.db.fetchall(
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
        ]

    def find_by_external(
        self, artifact_type: str, external_id: str, project: str, org: str | None = None
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM artifacts WHERE artifact_type = ? AND external_id = ? AND project = ?"
            + (" AND org = ?" if org is not None else ""),
            (artifact_type, external_id, project, org) if org is not None else (artifact_type, external_id, project),
        )

        return self._process_row(row) if row else None

    def list_all(
        self,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
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
        if artifact_type:
            where_clauses.append("artifact_type = ?")
            params.append(artifact_type)

        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        params.append(limit)

        return [
            self._process_row(row)
            for row in self.db.fetchall(
                f"SELECT * FROM artifacts {where_clause} ORDER BY created_at DESC LIMIT ?",
                params,
            )
        ]

    def list_for_projects(self, projects: list[str] | None = None, *, org: str | None = None) -> list[dict[str, Any]]:
        """Every artifact in *projects*, with ``raw_data`` parsed, oldest first."""
        if projects == []:
            return []
        clauses: list[str] = []
        params: list[Any] = []
        if projects is not None:
            clauses.append(f"project IN ({','.join('?' * len(projects))})")
            params.extend(projects)
        if org is not None:
            clauses.append("org = ?")
            params.append(org)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.fetchall(f"SELECT * FROM artifacts {where} ORDER BY created_at", params)
        return [self._process_row(row) for row in rows]

    def count(self, project: str | None = None, org: str | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("project", project), ("org", org)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        row = self.db.fetchone(f"SELECT COUNT(*) AS cnt FROM artifacts {where}", params)
        return row["cnt"] if row else 0
