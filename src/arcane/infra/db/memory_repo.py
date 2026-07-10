"""Memory repository — SQLite persistence for memories."""

from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timezone
from typing import Any

from arcane.infra.db.connection import Database

logger = logging.getLogger(__name__)

# Reserved org for the "applies everywhere" layer. Mirrors
# ``arcane.domain.scope.GLOBAL_ORG`` (kept local to avoid an infra→domain import).
GLOBAL_ORG = "global"


def _parse_tags(raw: Any) -> list[str]:
    """Deserialise tags from whatever shape the DB row delivers.

    Tags are stored as a JSON array string.  This helper normalises them so
    callers always receive ``list[str]`` — no json.loads scattered everywhere.
    """
    if isinstance(raw, list):
        return raw
    if raw and isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _process_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialise JSON fields on a raw DB row before returning to callers."""
    row["tags"] = _parse_tags(row.get("tags"))
    return row


class MemoryRepository:
    """CRUD operations for the memories table."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._vec_table_exists: bool | None = None

    def insert(self, mem: dict[str, Any], details: str | None = None) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO memories (
                id, title, what, why, impact, tags, category, project, org,
                source, related_files, file_path, section_anchor,
                created_at, updated_at, metadata, ttl_days, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mem["id"],
                mem["title"],
                mem["what"],
                mem.get("why"),
                mem.get("impact"),
                json.dumps(mem.get("tags", [])),
                mem.get("category"),
                mem["project"],
                mem.get("org", ""),
                mem.get("source"),
                json.dumps(mem.get("related_files", [])),
                mem.get("file_path", ""),
                mem.get("section_anchor", ""),
                mem["created_at"],
                mem["updated_at"],
                json.dumps(mem.get("metadata", {})),
                mem.get("ttl_days"),
                mem.get("confidence"),
            ),
        )
        rowid = cursor.lastrowid

        if details:
            self.db.execute(
                "INSERT INTO memory_details (memory_id, body) VALUES (?, ?)",
                (mem["id"], details),
            )

        self.db.commit()
        return rowid  # type: ignore[no-any-return]

    def get(self, memory_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT m.*,
                   EXISTS(SELECT 1 FROM memory_details WHERE memory_id = m.id) as has_details
            FROM memories m WHERE m.id = ?
            """,
            (memory_id,),
        )
        return _process_row(row) if row else None

    def get_many(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch multiple memories by exact ID in a single query."""
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self.db.fetchall(
            f"""
            SELECT m.*,
                   EXISTS(SELECT 1 FROM memory_details WHERE memory_id = m.id) as has_details
            FROM memories m WHERE m.id IN ({placeholders})
            """,
            memory_ids,
        )
        return [_process_row(r) for r in rows]

    def get_rowid(self, memory_id: str) -> int | None:
        """Return the SQLite rowid for *memory_id*, or ``None`` if not found."""
        row = self.db.fetchone("SELECT rowid FROM memories WHERE id = ?", (memory_id,))
        return row["rowid"] if row else None

    def get_details(self, memory_id: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            "SELECT memory_id, body FROM memory_details WHERE memory_id LIKE ?",
            (memory_id + "%",),
        )

    def resolve_prefix(self, id_prefix: str) -> str | None:
        """Return the full ID for a given prefix, or ``None`` if not found.

        Use this in CLI/MCP entry points where users supply short ID prefixes.
        Internal service code should always pass exact IDs.
        """
        row = self.db.fetchone("SELECT id FROM memories WHERE id LIKE ?", (id_prefix + "%",))
        return row["id"] if row else None

    def update(
        self,
        memory_id: str,
        what: str | None = None,
        why: str | None = None,
        impact: str | None = None,
        tags: list[str] | None = None,
        details_append: str | None = None,
    ) -> bool:
        """Update an existing memory by exact ID."""
        row = self.db.fetchone("SELECT id, rowid FROM memories WHERE id = ?", (memory_id,))
        if not row:
            # Fall back to prefix resolution for callers that pass short IDs
            row = self.db.fetchone("SELECT id, rowid FROM memories WHERE id LIKE ?", (memory_id + "%",))
        if not row:
            return False

        full_id = row["id"]
        now = datetime.now(timezone.utc).isoformat()
        sets = ["updated_count = updated_count + 1", "updated_at = ?"]
        params: list[Any] = [now]

        if what is not None:
            sets.append("what = ?")
            params.append(what)
        if why is not None:
            sets.append("why = ?")
            params.append(why)
        if impact is not None:
            sets.append("impact = ?")
            params.append(impact)
        if tags is not None:
            sets.append("tags = ?")
            params.append(json.dumps(tags))

        params.append(full_id)
        self.db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", params)

        if details_append:
            existing = self.db.fetchone("SELECT body FROM memory_details WHERE memory_id = ?", (full_id,))
            if existing:
                new_body = existing["body"] + "\n\n" + details_append
                self.db.execute(
                    "UPDATE memory_details SET body = ? WHERE memory_id = ?",
                    (new_body, full_id),
                )
            else:
                self.db.execute(
                    "INSERT INTO memory_details (memory_id, body) VALUES (?, ?)",
                    (full_id, details_append),
                )

        self.db.commit()
        return True

    def delete(self, memory_id: str) -> bool:
        row = self.db.fetchone("SELECT id FROM memories WHERE id = ?", (memory_id,))
        if not row:
            row = self.db.fetchone("SELECT id FROM memories WHERE id LIKE ?", (memory_id + "%",))
        if not row:
            return False

        full_id = row["id"]
        self.db.execute("DELETE FROM memory_details WHERE memory_id = ?", (full_id,))
        self.db.execute("DELETE FROM memories WHERE id = ?", (full_id,))
        self.db.commit()
        return True

    @staticmethod
    def _not_expired_clause() -> str:
        """SQL fragment that filters out expired memories (lazy expiry)."""
        return "(m.ttl_days IS NULL OR (unixepoch('now') - unixepoch(m.created_at)) < m.ttl_days * 86400)"

    @staticmethod
    def _scope_where(
        org: str,
        project: str | None,
        include_org: bool,
        include_global: bool,
        alias: str = "m",
    ) -> tuple[str, list[Any]]:
        """Build the scope WHERE fragment + params for the project ∪ org ∪ global chain."""
        layers: list[str] = []
        params: list[Any] = []
        if project:
            layers.append(f"({alias}.org = ? AND {alias}.project = ?)")
            params += [org, project]
        if include_org:
            layers.append(f"({alias}.org = ? AND COALESCE({alias}.project, '') = '')")
            params.append(org)
        if include_global:
            layers.append(f"{alias}.org = ?")
            params.append(GLOBAL_ORG)
        if not layers:  # degenerate (no project, both layers off) — match exact project layer
            layers.append(f"({alias}.org = ? AND {alias}.project = ?)")
            params += [org, project or ""]
        return "(" + " OR ".join(layers) + ")", params

    @staticmethod
    def _scope_rank_sql(org: str, project: str | None, alias: str = "m") -> tuple[str, list[Any]]:
        """A CASE expression ranking rows by specificity: project=3, org=2, global=1."""
        sql = (
            f"CASE WHEN {alias}.org = ? AND {alias}.project = ? THEN 3 "
            f"WHEN {alias}.org = ? AND COALESCE({alias}.project, '') = '' THEN 2 "
            f"WHEN {alias}.org = ? THEN 1 ELSE 0 END"
        )
        return sql, [org, project or "", org, GLOBAL_ORG]

    @staticmethod
    def _annotate_scope_rank(rows: list[dict[str, Any]], org: str, project: str | None) -> list[dict[str, Any]]:
        """Tag each row with a ``scope_rank`` (project=3, org=2, global=1, else 0)."""
        for r in rows:
            ro = r.get("org", "") or ""
            rp = r.get("project", "") or ""
            if project and ro == org and rp == project:
                r["scope_rank"] = 3
            elif ro == org and rp == "":
                r["scope_rank"] = 2
            elif ro == GLOBAL_ORG:
                r["scope_rank"] = 1
            else:
                r["scope_rank"] = 0
        return rows

    def list_projects(self) -> list[dict[str, Any]]:
        """Distinct (project, org) pairs with counts — for backfill and audits."""
        return self.db.fetchall(
            "SELECT project, org, COUNT(*) as cnt FROM memories GROUP BY project, org ORDER BY cnt DESC"
        )

    def reassign_project(self, old: str, new: str) -> int:
        """Move every memory in project *old* to *new*; return rows updated.

        The FTS index follows via the ``memories_au`` trigger.
        """
        cursor = self.db.execute("UPDATE memories SET project = ? WHERE project = ?", (new, old))
        self.db.commit()
        return int(cursor.rowcount)

    def fts_search(
        self,
        query: str,
        limit: int = 10,
        project: str | None = None,
        source: str | None = None,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        terms = query.split()
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"*' for term in terms)

        where_clauses: list[str] = [MemoryRepository._not_expired_clause()]
        params: list[Any] = [fts_query]

        if org is not None:
            scope_sql, scope_params = self._scope_where(org, project, include_org, include_global)
            where_clauses.append(scope_sql)
            params += scope_params
        elif project:
            where_clauses.append("m.project = ?")
            params.append(project)
        if source:
            where_clauses.append("m.source = ?")
            params.append(source)

        where_clause = "AND " + " AND ".join(where_clauses)

        params.append(limit)

        rows = self.db.fetchall(
            f"""
            SELECT m.*, -fts.rank as score,
                   EXISTS(SELECT 1 FROM memory_details WHERE memory_id = m.id) as has_details
            FROM memories_fts fts
            JOIN memories m ON m.rowid = fts.rowid
            WHERE fts.memories_fts MATCH ?
            {where_clause}
            ORDER BY fts.rank
            LIMIT ?
            """,
            params,
        )
        processed = [_process_row(r) for r in rows]
        if org is not None:
            self._annotate_scope_rank(processed, org, project)
        return processed

    def vector_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        project: str | None = None,
        source: str | None = None,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        """Return the nearest-neighbour memories for ``query_embedding``.

        Project/source/scope filters are applied inside SQL (via a JOIN
        condition) so that the ``limit`` guarantee is meaningful — we never burn
        our k budget on rows that will be discarded afterwards.
        """
        if not self._has_vec_table():
            return []

        # Fetch a wider candidate pool when filters are active so the final
        # result still has a chance of reaching ``limit`` rows.
        fetch_k = limit * 5 if (project or source or org is not None) else limit

        vec_bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)

        where_clauses: list[str] = ["v.embedding MATCH ?", "k = ?", MemoryRepository._not_expired_clause()]
        params: list[Any] = [vec_bytes, fetch_k]

        if org is not None:
            scope_sql, scope_params = self._scope_where(org, project, include_org, include_global)
            where_clauses.append(scope_sql)
            params += scope_params
        elif project:
            where_clauses.append("m.project = ?")
            params.append(project)
        if source:
            where_clauses.append("m.source = ?")
            params.append(source)

        where_sql = " AND ".join(where_clauses)

        rows = self.db.fetchall(
            f"""
            SELECT m.*, v.distance,
                   EXISTS(SELECT 1 FROM memory_details WHERE memory_id = m.id) as has_details
            FROM memories_vec v
            JOIN memories m ON m.rowid = v.rowid
            WHERE {where_sql}
            ORDER BY v.distance
            LIMIT ?
            """,
            params + [limit],
        )

        results = []
        for row in rows:
            row["score"] = 1.0 - row.pop("distance")
            results.append(_process_row(row))

        if org is not None:
            self._annotate_scope_rank(results, org, project)
        return results

    def list_recent(
        self,
        limit: int = 10,
        project: str | None = None,
        source: str | None = None,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        select_rank = ""

        # SELECT-clause params (scope rank) come first in the SQL text.
        if org is not None:
            rank_sql, rank_params = self._scope_rank_sql(org, project)
            select_rank = f", ({rank_sql}) AS scope_rank"
            params += rank_params

        where_clauses: list[str] = [MemoryRepository._not_expired_clause()]
        if org is not None:
            scope_sql, scope_params = self._scope_where(org, project, include_org, include_global)
            where_clauses.append(scope_sql)
            params += scope_params
        elif project:
            where_clauses.append("m.project = ?")
            params.append(project)
        if source:
            where_clauses.append("m.source = ?")
            params.append(source)

        where_clause = "WHERE " + " AND ".join(where_clauses)
        order_by = "ORDER BY scope_rank DESC, m.created_at DESC" if org is not None else "ORDER BY m.created_at DESC"

        params.append(limit)

        rows = self.db.fetchall(
            f"""
            SELECT m.*, EXISTS(SELECT 1 FROM memory_details WHERE memory_id = m.id) as has_details{select_rank}
            FROM memories m
            {where_clause}
            {order_by}
            LIMIT ?
            """,
            params,
        )
        return [_process_row(r) for r in rows]

    def list_all_for_reindex(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT rowid, title, what, why, impact, tags FROM memories ORDER BY rowid")
        return [_process_row(r) for r in rows]

    def count(
        self,
        project: str | None = None,
        source: str | None = None,
        org: str | None = None,
        include_org: bool = True,
        include_global: bool = True,
    ) -> int:
        where_clauses: list[str] = [MemoryRepository._not_expired_clause()]
        params: list[Any] = []

        if org is not None:
            scope_sql, scope_params = self._scope_where(org, project, include_org, include_global)
            where_clauses.append(scope_sql)
            params += scope_params
        elif project:
            where_clauses.append("m.project = ?")
            params.append(project)
        if source:
            where_clauses.append("m.source = ?")
            params.append(source)

        where_clause = "WHERE " + " AND ".join(where_clauses)

        row = self.db.fetchone(f"SELECT COUNT(*) as cnt FROM memories m {where_clause}", params)
        return row["cnt"] if row else 0

    def insert_vector(self, rowid: int, embedding: list[float]) -> None:
        """Upsert a vector for *rowid* into the vec0 table.

        vec0 virtual tables do not support ``INSERT OR REPLACE``, so we delete
        the existing row first (if any) then insert.
        """
        if not self._has_vec_table():
            return
        vec_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        self.db.execute("DELETE FROM memories_vec WHERE rowid = ?", (rowid,))
        self.db.execute(
            "INSERT INTO memories_vec (rowid, embedding) VALUES (?, ?)",
            (rowid, vec_bytes),
        )
        self.db.commit()

    def _has_vec_table(self) -> bool:
        """Return whether the vector table exists, caching the result."""
        if self._vec_table_exists is None:
            row = self.db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='memories_vec'")
            self._vec_table_exists = row is not None
        return self._vec_table_exists

    def invalidate_vec_cache(self) -> None:
        """Force ``_has_vec_table`` to re-query on next access."""
        self._vec_table_exists = None

    # Meta helpers
    def get_meta(self, key: str) -> str | None:
        row = self.db.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def get_embedding_dim(self) -> int | None:
        val = self.get_meta("embedding_dim")
        return int(val) if val is not None else None

    def set_embedding_dim(self, dim: int) -> None:
        self.set_meta("embedding_dim", str(dim))

    def drop_vec_table(self) -> None:
        self.db.execute("DROP TABLE IF EXISTS memories_vec")
        self.db.commit()
        self._vec_table_exists = False
