"""Relationship repository — SQLite persistence for entity relationships."""

from __future__ import annotations

from typing import Any

from arcane.infra.db.connection import Database


class RelationshipRepository:
    """CRUD operations for the relationships table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, rel: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO relationships (
                id, source_type, source_id, target_type, target_id, relation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rel["id"], rel["source_type"], rel["source_id"],
                rel["target_type"], rel["target_id"],
                rel["relation"], rel["created_at"],
            ),
        )
        self.db.commit()

    def get_from(self, source_type: str, source_id: str) -> list[dict[str, Any]]:
        return self.db.fetchall(
            "SELECT * FROM relationships WHERE source_type = ? AND source_id LIKE ?",
            (source_type, source_id + "%"),
        )

    def get_to(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        return self.db.fetchall(
            "SELECT * FROM relationships WHERE target_type = ? AND target_id LIKE ?",
            (target_type, target_id + "%"),
        )

    def get_all_for(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        """Get all relationships where this entity is source or target."""
        outgoing = self.get_from(entity_type, entity_id)
        incoming = self.get_to(entity_type, entity_id)
        return outgoing + incoming

    def trace(
        self, entity_type: str, entity_id: str, max_depth: int = 5
    ) -> list[dict[str, Any]]:
        """Walk the relationship graph from an entity, returning all connected edges."""
        visited: set[str] = set()
        result: list[dict[str, Any]] = []
        queue: list[tuple[str, str, int]] = [(entity_type, entity_id, 0)]

        while queue:
            etype, eid, depth = queue.pop(0)
            if depth > max_depth:
                continue

            key = f"{etype}:{eid}"
            if key in visited:
                continue
            visited.add(key)

            rels = self.get_all_for(etype, eid)
            for rel in rels:
                if rel["id"] not in {r["id"] for r in result}:
                    result.append(rel)

                other_type = rel["target_type"] if rel["source_id"].startswith(eid) else rel["source_type"]
                other_id = rel["target_id"] if rel["source_id"].startswith(eid) else rel["source_id"]
                other_key = f"{other_type}:{other_id}"
                if other_key not in visited:
                    queue.append((other_type, other_id, depth + 1))

        return result

    def delete(self, rel_id: str) -> bool:
        row = self.db.fetchone("SELECT id FROM relationships WHERE id = ?", (rel_id,))
        if not row:
            return False
        self.db.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
        self.db.commit()
        return True

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(*) as cnt FROM relationships")
        return row["cnt"] if row else 0
