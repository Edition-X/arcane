"""Database schema creation and migrations."""

from __future__ import annotations

import re

from arcane.infra.db.connection import Database
from arcane.infra.db.ids import ENTITY_TABLES, IdentifierResolutionError, resolve_unique_id

RELATIONSHIP_REPAIR_KEY = "relationship_ids_repaired"

# Legacy health and usage insights summarise the whole vault, so no single
# org owns them. Ownership backfill and recovery both skip them.
SCOPED_INSIGHT_TYPES = (
    "insight_type NOT IN ('health', 'usage') "
    "AND substr(insight_type, 1, 7) != 'health_' AND substr(insight_type, 1, 6) != 'usage_'"
)


def create_schema(db: Database) -> None:
    """Create all tables, triggers, and indexes. Idempotent."""

    # ── memories (EchoVault-compatible) ──────────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            what TEXT NOT NULL,
            why TEXT,
            impact TEXT,
            tags TEXT,
            category TEXT,
            project TEXT NOT NULL,
            source TEXT,
            related_files TEXT,
            file_path TEXT NOT NULL,
            section_anchor TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_details (
            memory_id TEXT PRIMARY KEY REFERENCES memories(id),
            body TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # FTS5 virtual table
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            title, what, why, impact, tags, category, project, source,
            content='memories', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    # FTS auto-sync triggers
    db.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, title, what, why, impact, tags, category, project, source)
            VALUES (new.rowid, new.title, new.what, new.why, new.impact, new.tags, new.category, new.project, new.source);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, title, what, why, impact, tags, category, project, source)
            VALUES ('delete', old.rowid, old.title, old.what, old.why, old.impact, old.tags, old.category, old.project, old.source);
            INSERT INTO memories_fts(rowid, title, what, why, impact, tags, category, project, source)
            VALUES (new.rowid, new.title, new.what, new.why, new.impact, new.tags, new.category, new.project, new.source);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, title, what, why, impact, tags, category, project, source)
            VALUES ('delete', old.rowid, old.title, old.what, old.why, old.impact, old.tags, old.category, old.project, old.source);
        END
    """)

    # Migration: add columns if missing
    _add_column_if_missing(db, "memories", "updated_count", "INTEGER DEFAULT 0")
    _add_column_if_missing(db, "memories", "metadata", "TEXT DEFAULT '{}'")
    _add_column_if_missing(db, "memories", "ttl_days", "INTEGER")
    _add_column_if_missing(db, "memories", "confidence", "REAL")
    _add_column_if_missing(db, "memories", "org", "TEXT NOT NULL DEFAULT ''")

    # ── journeys ────────────────────────────────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS journeys (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            project TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            summary TEXT,
            linear_issue_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS journeys_fts USING fts5(
            title, summary, project,
            content='journeys', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS journeys_ai AFTER INSERT ON journeys BEGIN
            INSERT INTO journeys_fts(rowid, title, summary, project)
            VALUES (new.rowid, new.title, new.summary, new.project);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS journeys_au AFTER UPDATE ON journeys BEGIN
            INSERT INTO journeys_fts(journeys_fts, rowid, title, summary, project)
            VALUES ('delete', old.rowid, old.title, old.summary, old.project);
            INSERT INTO journeys_fts(rowid, title, summary, project)
            VALUES (new.rowid, new.title, new.summary, new.project);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS journeys_ad AFTER DELETE ON journeys BEGIN
            INSERT INTO journeys_fts(journeys_fts, rowid, title, summary, project)
            VALUES ('delete', old.rowid, old.title, old.summary, old.project);
        END
    """)

    # ── artifacts ───────────────────────────────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL,
            artifact_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            raw_data TEXT,
            project TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(artifact_type, external_id, project)
        )
    """)

    artifact_fts_exists = (
        db.fetchone("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'artifacts_fts'") is not None
    )
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
            title, artifact_type, external_id, project, raw_data,
            content='artifacts', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS artifacts_ai AFTER INSERT ON artifacts BEGIN
            INSERT INTO artifacts_fts(rowid, title, artifact_type, external_id, project, raw_data)
            VALUES (new.rowid, new.title, new.artifact_type, new.external_id, new.project, new.raw_data);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS artifacts_au AFTER UPDATE ON artifacts BEGIN
            INSERT INTO artifacts_fts(artifacts_fts, rowid, title, artifact_type, external_id, project, raw_data)
            VALUES ('delete', old.rowid, old.title, old.artifact_type, old.external_id, old.project, old.raw_data);
            INSERT INTO artifacts_fts(rowid, title, artifact_type, external_id, project, raw_data)
            VALUES (new.rowid, new.title, new.artifact_type, new.external_id, new.project, new.raw_data);
        END
    """)

    db.execute("""
        CREATE TRIGGER IF NOT EXISTS artifacts_ad AFTER DELETE ON artifacts BEGIN
            INSERT INTO artifacts_fts(artifacts_fts, rowid, title, artifact_type, external_id, project, raw_data)
            VALUES ('delete', old.rowid, old.title, old.artifact_type, old.external_id, old.project, old.raw_data);
        END
    """)

    if not artifact_fts_exists:
        # Existing databases predate artifact FTS. Rebuild keeps previously
        # ingested raw content discoverable after an upgrade.
        db.execute("INSERT INTO artifacts_fts(artifacts_fts) VALUES ('rebuild')")

    db.execute("""
        CREATE TABLE IF NOT EXISTS journey_events (
            id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # ── relationships ───────────────────────────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_rel_source
        ON relationships(source_type, source_id)
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_rel_target
        ON relationships(target_type, target_id)
    """)

    # ── insights ────────────────────────────────────────────────────────
    db.execute("""
        CREATE TABLE IF NOT EXISTS insights (
            id TEXT PRIMARY KEY,
            insight_type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            project TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            acknowledged INTEGER DEFAULT 0
        )
    """)

    _migrate_entity_orgs(db)

    # ── retrievals ──────────────────────────────────────────────────────
    # One row per MCP lookup, and one hit per entity it returned, so usage
    # analysis can tell recalled memories from ones nobody ever reads.
    db.execute("""
        CREATE TABLE IF NOT EXISTS retrievals (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            client TEXT,
            tool TEXT NOT NULL,
            org TEXT,
            project TEXT,
            query TEXT,
            result_count INTEGER NOT NULL DEFAULT 0,
            keyword_matches INTEGER,
            duration_ms INTEGER,
            is_error INTEGER NOT NULL DEFAULT 0
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS retrieval_hits (
            retrieval_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            PRIMARY KEY (retrieval_id, entity_type, entity_id)
        )
    """)
    # Added during the table's first release; a store created by a pre-release build lacks it.
    _add_column_if_missing(db, "retrievals", "keyword_matches", "INTEGER")

    # ── Performance indexes ─────────────────────────────────────────────
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_org ON memories(org)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_org_project ON memories(org, project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_ttl ON memories(ttl_days, created_at)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_project ON journeys(project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_status ON journeys(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_project_status ON journeys(project, status)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project)")
    # Duplicates of the implicit PRIMARY KEY / UNIQUE indexes; they only slowed writes.
    db.execute("DROP INDEX IF EXISTS idx_mem_details_id")
    db.execute("DROP INDEX IF EXISTS idx_artifacts_type_ext_proj")

    db.execute("CREATE INDEX IF NOT EXISTS idx_journey_events_journey ON journey_events(journey_id, created_at)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_insights_project ON insights(project)")
    for table in ("journeys", "artifacts", "insights"):
        db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_org_project ON {table}(org, project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_insights_ack ON insights(acknowledged, project)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_retrievals_created ON retrievals(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_retrievals_session ON retrievals(session_id, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_hits_entity ON retrieval_hits(entity_type, entity_id)")

    db.commit()

    _repair_relationship_ids(db)
    _heal_renamed_vec_table(db)

    # Create vec table if dimension already known
    dim = _get_meta(db, "embedding_dim")
    if dim is not None:
        create_vec_table(db, int(dim))


def create_vec_table(db: Database, dim: int) -> None:
    """Create the vector similarity table with given dimension.

    A no-op where sqlite-vec could not be loaded: the caller has an embedding
    but nowhere to put it, and search falls back to FTS5.
    """
    if not db.vec_available:
        return
    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
            rowid INTEGER PRIMARY KEY,
            embedding float[{dim}]
        )
    """)
    db.commit()


def _heal_renamed_vec_table(db: Database) -> None:
    """Repair a ``memories_vec`` left broken by an older ``arcane reindex``.

    That reindex built ``memories_vec_staging`` and renamed it to
    ``memories_vec``, but vec0 keeps its shadow tables under the old name, so
    every read or write of the renamed table failed. Renaming the shadow
    tables to match makes the table (and its rebuilt vectors) usable again.
    """
    names = {
        row["name"]
        for row in db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'memories_vec%'")
    }
    if "memories_vec" not in names or "memories_vec_rowids" in names or "memories_vec_staging_rowids" not in names:
        return
    staging_prefix = "memories_vec_staging_"
    with db.transaction():
        for name in sorted(names):
            if name.startswith(staging_prefix):
                db.execute(f"ALTER TABLE {name} RENAME TO memories_vec_{name[len(staging_prefix) :]}")


def _repair_relationship_ids(db: Database) -> None:
    """Expand relationship endpoints stored as ID prefixes to full IDs. Runs once.

    Older write paths stored whatever prefix the caller typed, but lookups
    match exact IDs, so those edges never showed up in journey_show or trace.
    A prefix that no longer identifies exactly one entity is left untouched.
    """
    if _get_meta(db, RELATIONSHIP_REPAIR_KEY) is not None:
        return
    with db.transaction():
        for id_column, type_column in (("source_id", "source_type"), ("target_id", "target_type")):
            for entity_type, table in ENTITY_TABLES.items():
                rows = db.fetchall(
                    f"SELECT r.id, r.{id_column} AS ref FROM relationships r WHERE r.{type_column} = ? "
                    f"AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = r.{id_column})",
                    (entity_type,),
                )
                for row in rows:
                    try:
                        full_id = resolve_unique_id(db, table, row["ref"] or "")
                    except IdentifierResolutionError:
                        continue
                    if full_id is not None:
                        db.execute(f"UPDATE relationships SET {id_column} = ? WHERE id = ?", (full_id, row["id"]))
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, '1')", (RELATIONSHIP_REPAIR_KEY,))


def _add_column_if_missing(db: Database, table: str, column: str, definition: str) -> None:
    rows = db.fetchall(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in rows}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_entity_orgs(db: Database) -> None:
    """Record ownership once, without guessing the owner of shared project names.

    Empty org means unknown for legacy entities. Even a majority of memories
    cannot establish ownership: every memory for the project must agree on one
    nonempty org. Do not revisit unknown rows on subsequent startups, when the
    evidence may have changed or been deleted.
    """
    key = "entity_orgs_migrated"
    if _get_meta(db, key) is not None:
        return
    db.commit()
    with db.transaction():
        # Recheck after acquiring the write lock: another process may migrate.
        if _get_meta(db, key) is not None:
            return
        for table in ("journeys", "artifacts", "insights"):
            _add_column_if_missing(db, table, "org", "TEXT NOT NULL DEFAULT ''")
            # Legacy health/usage bodies describe the whole vault, even when
            # their attached project has a unique owner. They need review via
            # `migrate entity-org`, rather than silently entering an org export.
            safe_insight = f" AND {SCOPED_INSIGHT_TYPES}" if table == "insights" else ""
            db.execute(f"""
                UPDATE {table} SET org = (
                    SELECT MIN(m.org) FROM memories m WHERE m.project = {table}.project
                ) WHERE org = '' AND project <> '' AND project IN (
                    SELECT project FROM memories GROUP BY project
                    HAVING COUNT(DISTINCT org) = 1 AND MIN(org) <> ''
                ){safe_insight}
            """)

        # SQLite cannot drop an inline UNIQUE constraint. Rebuild the ordinary
        # table, preserving rowids (FTS references them), indexes and triggers.
        # The external-content FTS table itself must keep its original name.
        old_unique = any(
            [c["name"] for c in db.fetchall("SELECT name FROM pragma_index_info(?)", (index["name"],))]
            == ["artifact_type", "external_id", "project"]
            for index in db.fetchall("PRAGMA index_list(artifacts)")
            if index["unique"]
        )
        if old_unique:
            sequence = db.fetchone("SELECT seq FROM sqlite_sequence WHERE name = 'artifacts'")
            row = db.fetchone("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'artifacts'")
            assert row is not None
            ddl, count = re.subn(
                r"UNIQUE\s*\(\s*artifact_type\s*,\s*external_id\s*,\s*project\s*\)",
                "UNIQUE(artifact_type, external_id, project, org)",
                row["sql"],
                flags=re.IGNORECASE,
            )
            if count != 1:
                raise RuntimeError("Cannot safely migrate artifacts ownership constraint")
            ddl = re.sub(r"\bartifacts\b", "artifacts_org_migration", ddl, count=1)
            objects = db.fetchall(
                "SELECT sql FROM sqlite_master WHERE tbl_name = 'artifacts' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            )
            db.execute(ddl)
            db.execute("INSERT INTO artifacts_org_migration SELECT * FROM artifacts")
            db.execute("DROP TABLE artifacts")
            db.execute("ALTER TABLE artifacts_org_migration RENAME TO artifacts")
            if sequence is not None:
                db.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'artifacts'", (sequence["seq"],))
            for obj in objects:
                db.execute(obj["sql"])
        db.execute("INSERT INTO meta (key, value) VALUES (?, '1')", (key,))


def _get_meta(db: Database, key: str) -> str | None:
    row = db.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None
