"""Retrieval repository — what MCP lookups returned, and usage queries over it."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from arcane.infra.db.connection import Database
from arcane.infra.db.fts import key_terms_query

# Lookups that put memories in front of an agent, and the follow-ups that show
# one was worth opening.
RECALL_TOOLS = ("memory_search", "memory_context", "resource_context")
FOLLOW_UP_TOOLS = ("memory_details", "memory_update")


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class RetrievalRepository:
    """Append-only lookup log with retention and usage aggregates."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, event: dict[str, Any], hits: list[tuple[str, str]]) -> str:
        """Store one lookup and the ``(entity_type, entity_id)`` hits it returned, in rank order."""
        retrieval_id = str(uuid.uuid4())
        seen: set[tuple[str, str]] = set()
        rows = []
        for rank, hit in enumerate(hits):
            if hit in seen:
                continue
            seen.add(hit)
            rows.append((retrieval_id, hit[0], hit[1], rank))
        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO retrievals (
                    id, created_at, session_id, client, tool, org, project, query,
                    result_count, keyword_matches, duration_ms, is_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_id,
                    event.get("created_at") or datetime.now(timezone.utc).isoformat(),
                    event["session_id"],
                    event.get("client"),
                    event["tool"],
                    event.get("org"),
                    event.get("project"),
                    event.get("query"),
                    len(rows),
                    event.get("keyword_matches"),
                    event.get("duration_ms"),
                    1 if event.get("is_error") else 0,
                ),
            )
            if rows:
                self.db.executemany(
                    "INSERT INTO retrieval_hits (retrieval_id, entity_type, entity_id, rank) VALUES (?, ?, ?, ?)",
                    rows,
                )
        return retrieval_id

    def keyword_matches(self, text: str) -> int | None:
        """How many memories contain the key words of *text*, store-wide; ``None`` without key words.

        Vector search always returns its nearest neighbours, so a result count
        cannot show a search that found nothing relevant. Zero here can.
        """
        expr = key_terms_query(text)
        if expr is None:
            return None
        row = self.db.fetchone("SELECT count(*) AS n FROM memories_fts WHERE memories_fts MATCH ?", (expr,))
        return int(row["n"]) if row else 0

    def prune(self, retention_days: int) -> int:
        """Delete lookups older than *retention_days*; return how many went."""
        cutoff = _since(retention_days)
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM retrieval_hits WHERE retrieval_id IN (SELECT id FROM retrievals WHERE created_at < ?)",
                (cutoff,),
            )
            cursor = self.db.execute("DELETE FROM retrievals WHERE created_at < ?", (cutoff,))
        return int(cursor.rowcount)

    def count(self) -> int:
        row = self.db.fetchone("SELECT count(*) AS n FROM retrievals")
        return int(row["n"]) if row else 0

    def first_recorded(self) -> str | None:
        row = self.db.fetchone("SELECT min(created_at) AS first FROM retrievals")
        return row["first"] if row else None

    # ── usage aggregates ────────────────────────────────────────────────

    def by_client(self, days: int) -> list[dict[str, Any]]:
        return self.db.fetchall(
            """
            SELECT coalesce(client, 'unknown') AS client, count(*) AS lookups,
                   count(DISTINCT session_id) AS sessions
            FROM retrievals WHERE created_at >= ?
            GROUP BY 1 ORDER BY lookups DESC
            """,
            (_since(days),),
        )

    def by_tool(self, days: int) -> list[dict[str, Any]]:
        return self.db.fetchall(
            "SELECT tool, count(*) AS lookups FROM retrievals WHERE created_at >= ? GROUP BY 1 ORDER BY 2 DESC",
            (_since(days),),
        )

    # A search is a possible gap when it returned nothing, or when no memory
    # contains its key words (so whatever came back was a weak match).
    _GAP = "(result_count = 0 OR keyword_matches = 0)"
    _SEARCHED = (
        "created_at >= ? AND tool IN ('memory_search', 'memory_context') "
        "AND query IS NOT NULL AND query != '' AND is_error = 0"
    )

    def searches(self, days: int) -> dict[str, int]:
        """Searches with text, how many returned nothing, and how many were possible gaps."""
        row = self.db.fetchone(
            f"""
            SELECT count(*) AS total, coalesce(sum(result_count = 0), 0) AS empty,
                   coalesce(sum({self._GAP}), 0) AS gaps
            FROM retrievals WHERE {self._SEARCHED}
            """,
            (_since(days),),
        )
        if not row:
            return {"total": 0, "empty": 0, "gaps": 0}
        return {"total": int(row["total"]), "empty": int(row["empty"]), "gaps": int(row["gaps"])}

    def gap_queries(self, days: int, limit: int = 10) -> list[dict[str, Any]]:
        """Possible-gap search text, most frequent first."""
        return self.db.fetchall(
            f"""
            SELECT query, count(*) AS times, max(created_at) AS last_at, max(project) AS project,
                   max(result_count) AS results
            FROM retrievals WHERE {self._SEARCHED} AND {self._GAP}
            GROUP BY lower(query) ORDER BY times DESC, last_at DESC LIMIT ?
            """,
            (_since(days), limit),
        )

    def follow_through(self, days: int) -> dict[str, int]:
        """Recall lookups with results, and how many led to opening or updating one of them."""
        row = self.db.fetchone(
            f"""
            SELECT count(*) AS total, coalesce(sum(EXISTS (
                SELECT 1
                FROM retrieval_hits h
                JOIN retrieval_hits h2 ON h2.entity_type = 'memory' AND h2.entity_id = h.entity_id
                JOIN retrievals r2 ON r2.id = h2.retrieval_id
                WHERE h.retrieval_id = r.id AND h.entity_type = 'memory'
                  AND r2.session_id = r.session_id AND r2.created_at >= r.created_at
                  AND r2.tool IN ({",".join("?" * len(FOLLOW_UP_TOOLS))})
            )), 0) AS followed
            FROM retrievals r
            WHERE r.created_at >= ? AND r.result_count > 0
              AND r.tool IN ({",".join("?" * len(RECALL_TOOLS))})
            """,
            (*FOLLOW_UP_TOOLS, _since(days), *RECALL_TOOLS),
        )
        return {"total": int(row["total"]), "followed": int(row["followed"])} if row else {"total": 0, "followed": 0}

    def replaced_hits(self, days: int) -> dict[str, int]:
        """Lookups that returned a memory a newer one has replaced, and how many such hits."""
        row = self.db.fetchone(
            """
            SELECT count(DISTINCT h.retrieval_id) AS lookups, count(*) AS hits
            FROM retrieval_hits h JOIN retrievals r ON r.id = h.retrieval_id
            WHERE h.entity_type = 'memory' AND r.created_at >= ? AND h.entity_id IN (
                SELECT target_id FROM relationships WHERE relation = 'supersedes' AND target_type = 'memory'
            )
            """,
            (_since(days),),
        )
        return {"lookups": int(row["lookups"]), "hits": int(row["hits"])} if row else {"lookups": 0, "hits": 0}

    def top_memories(self, days: int, limit: int = 10) -> list[dict[str, Any]]:
        return self.db.fetchall(
            """
            SELECT m.id, m.title, m.project, count(*) AS hits
            FROM retrieval_hits h
            JOIN retrievals r ON r.id = h.retrieval_id
            JOIN memories m ON m.id = h.entity_id
            WHERE h.entity_type = 'memory' AND r.created_at >= ?
            GROUP BY m.id ORDER BY hits DESC, m.created_at DESC LIMIT ?
            """,
            (_since(days), limit),
        )

    def never_recalled(self, older_than_days: int) -> dict[str, Any]:
        """Memories older than *older_than_days* that no recorded lookup has returned."""
        cutoff = _since(older_than_days)
        where = """
            FROM memories m
            WHERE m.created_at < ? AND NOT EXISTS (
                SELECT 1 FROM retrieval_hits h WHERE h.entity_type = 'memory' AND h.entity_id = m.id
            )
        """
        total = self.db.fetchone(f"SELECT count(*) AS n {where}", (cutoff,))
        by_project = self.db.fetchall(
            f"SELECT coalesce(nullif(m.project, ''), '(none)') AS project, count(*) AS n {where} "
            "GROUP BY 1 ORDER BY n DESC LIMIT 10",
            (cutoff,),
        )
        eligible = self.db.fetchone("SELECT count(*) AS n FROM memories WHERE created_at < ?", (cutoff,))
        return {
            "count": int(total["n"]) if total else 0,
            "eligible": int(eligible["n"]) if eligible else 0,
            "by_project": by_project,
        }
