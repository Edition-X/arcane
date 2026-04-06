"""Tests for the MigrationService — EchoVault → Arcane migration."""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from arcane.services.migration import MigrationService


@pytest.fixture
def echovault_home(tmp_path):
    """Create a fake EchoVault home directory with schema and data."""
    home = tmp_path / "echovault"
    home.mkdir()
    vault = home / "vault" / "test-project"
    vault.mkdir(parents=True)
    (vault / "2026-03-21-session.md").write_text("# Session\n## Test Memory\n")

    # Create EchoVault-compatible database
    db_path = str(home / "index.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE memories (
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
    conn.execute("""
        CREATE TABLE memory_details (
            memory_id TEXT PRIMARY KEY REFERENCES memories(id),
            body TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            title, what, why, impact, tags, category, project, source,
            content='memories', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)
    # Manually add FTS triggers
    conn.execute("""
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, title, what, why, impact, tags, category, project, source)
            VALUES (new.rowid, new.title, new.what, new.why, new.impact, new.tags, new.category, new.project, new.source);
        END
    """)

    # Insert test memories
    for i in range(5):
        conn.execute(
            """INSERT INTO memories (id, title, what, why, impact, tags, category, project,
               source, related_files, file_path, section_anchor, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"mem-{i:04d}",
                f"Memory {i}",
                f"What {i}",
                f"Why {i}",
                None,
                json.dumps(["tag1"]),
                "context",
                "test-project",
                None,
                json.dumps([]),
                f"/tmp/test-{i}.md",
                f"memory-{i}",
                "2026-03-21T10:00:00+00:00",
                "2026-03-21T10:00:00+00:00",
            ),
        )

    conn.execute("INSERT INTO memory_details (memory_id, body) VALUES ('mem-0000', 'Full details for memory 0')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('embedding_dim', '768')")
    conn.commit()
    conn.close()

    # Config
    (home / "config.yaml").write_text("embedding:\n  provider: ollama\n  model: nomic-embed-text\n")
    (home / ".memoryignore").write_text("SECRET_KEY\nAPI_TOKEN\n")

    return str(home)


@pytest.fixture
def arcane_home(tmp_path):
    """Empty Arcane home directory."""
    home = tmp_path / "arcane"
    home.mkdir()
    return str(home)


class TestMigrationService:
    def test_migrate_copies_database(self, echovault_home, arcane_home):
        svc = MigrationService()
        result = svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        assert result["success"] is True
        assert result["memory_count"] == 5
        assert os.path.exists(os.path.join(arcane_home, "index.db"))

    def test_migrate_upgrades_schema(self, echovault_home, arcane_home):
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        # Check new tables exist
        from arcane.infra.db.connection import Database

        db = Database(os.path.join(arcane_home, "index.db"))
        tables = {r["name"] for r in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        db.close()

        assert "journeys" in tables
        assert "artifacts" in tables
        assert "relationships" in tables
        assert "insights" in tables

    def test_migrate_adds_new_columns(self, echovault_home, arcane_home):
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        from arcane.infra.db.connection import Database

        db = Database(os.path.join(arcane_home, "index.db"))
        cols = {r["name"] for r in db.fetchall("PRAGMA table_info(memories)")}
        db.close()

        assert "updated_count" in cols
        assert "metadata" in cols

    def test_migrate_copies_vault(self, echovault_home, arcane_home):
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        session_file = os.path.join(arcane_home, "vault", "test-project", "2026-03-21-session.md")
        assert os.path.exists(session_file)

    def test_migrate_copies_config(self, echovault_home, arcane_home):
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        assert os.path.exists(os.path.join(arcane_home, "config.yaml"))
        assert os.path.exists(os.path.join(arcane_home, ".memoryignore"))

    def test_migrate_skips_existing_db(self, echovault_home, arcane_home):
        """If target DB already exists, skip copy and note it."""
        # Create existing target DB
        os.makedirs(arcane_home, exist_ok=True)
        open(os.path.join(arcane_home, "index.db"), "w").close()

        svc = MigrationService()
        result = svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        assert result["success"] is True
        assert any("already exists" in e for e in result.get("errors", []))

    def test_migrate_missing_source(self, tmp_path, arcane_home):
        svc = MigrationService()
        result = svc.migrate_from_echovault(
            source_home=str(tmp_path / "nonexistent"),
            target_home=arcane_home,
        )
        assert result["success"] is False

    def test_verify_after_migration(self, echovault_home, arcane_home):
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        result = svc.verify(home=arcane_home)
        assert result["success"] is True
        assert result["memories_count"] == 5
        assert result["fts_synced"] is True
        assert result["embedding_dim"] == 768

    def test_verify_missing_db(self, tmp_path):
        svc = MigrationService()
        result = svc.verify(home=str(tmp_path / "nope"))
        assert result["success"] is False

    def test_memories_searchable_after_migration(self, echovault_home, arcane_home):
        """Migrated memories should be searchable via FTS."""
        svc = MigrationService()
        svc.migrate_from_echovault(source_home=echovault_home, target_home=arcane_home)

        from arcane.infra.db.connection import Database
        from arcane.infra.db.memory_repo import MemoryRepository

        db = Database(os.path.join(arcane_home, "index.db"))
        repo = MemoryRepository(db)

        results = repo.fts_search("Memory", limit=10)
        assert len(results) >= 1
        db.close()


def test_migrate_adds_ttl_and_confidence_columns(db):
    """After schema creation, memories table must have ttl_days and confidence."""
    rows = db.fetchall("PRAGMA table_info(memories)")
    cols = {r["name"] for r in rows}
    assert "ttl_days" in cols
    assert "confidence" in cols
