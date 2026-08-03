"""Database schema creation and migrations."""

from __future__ import annotations

from arcane.infra.db.connection import Database


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

    # ── Performance indexes ─────────────────────────────────────────────
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_org ON memories(org)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_org_project ON memories(org, project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_ttl ON memories(ttl_days, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mem_details_id ON memory_details(memory_id)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_project ON journeys(project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_status ON journeys(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_journeys_project_status ON journeys(project, status)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_artifacts_type_ext_proj ON artifacts(artifact_type, external_id, project)"
    )

    db.execute("CREATE INDEX IF NOT EXISTS idx_journey_events_journey ON journey_events(journey_id, created_at)")

    db.execute("CREATE INDEX IF NOT EXISTS idx_insights_project ON insights(project)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_insights_ack ON insights(acknowledged, project)")

    db.commit()

    # Create vec table if dimension already known
    dim = _get_meta(db, "embedding_dim")
    if dim is not None:
        create_vec_table(db, int(dim))


def create_vec_table(db: Database, dim: int) -> None:
    """Create the vector similarity table with given dimension."""
    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
            rowid INTEGER PRIMARY KEY,
            embedding float[{dim}]
        )
    """)
    db.commit()


def _add_column_if_missing(db: Database, table: str, column: str, definition: str) -> None:
    rows = db.fetchall(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in rows}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _get_meta(db: Database, key: str) -> str | None:
    row = db.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None
