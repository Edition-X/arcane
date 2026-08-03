"""Integration tests for searchable artifact persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from arcane.infra.db.connection import Database
from arcane.infra.db.schema import create_schema


def make_artifact(**overrides: object) -> dict[str, object]:
    artifact = {
        "id": str(uuid.uuid4()),
        "artifact_type": "commit",
        "external_id": "abc123",
        "title": "Fix authentication timeout",
        "url": "https://example.test/commit/abc123",
        "raw_data": {"body": "Retries now use exponential backoff"},
        "project": "arcane",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact.update(overrides)
    return artifact


def test_fts_searches_artifact_raw_data(artifact_repo):
    artifact = make_artifact()
    artifact_repo.insert(artifact)

    results = artifact_repo.fts_search("exponential backoff", project="arcane")

    assert [result["id"] for result in results] == [artifact["id"]]


def test_schema_backfills_existing_artifacts_into_fts(tmp_path):
    db = Database(str(tmp_path / "arcane.db"))
    db.execute("""
        CREATE TABLE artifacts (
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
    db.execute(
        """INSERT INTO artifacts (id, artifact_type, external_id, title, raw_data, project, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "legacy-artifact",
            "ci_run",
            "42",
            "Legacy CI run",
            '{"conclusion":"failure","workflow":"release"}',
            "arcane",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()

    create_schema(db)

    results = db.fetchall(
        """SELECT artifacts.id FROM artifacts
        JOIN artifacts_fts ON artifacts.rowid = artifacts_fts.rowid
        WHERE artifacts_fts MATCH ?""",
        ("failure",),
    )
    db.close()
    assert results == [{"id": "legacy-artifact"}]
