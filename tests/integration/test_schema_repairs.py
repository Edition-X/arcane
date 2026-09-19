"""One-time repairs and schema fixes applied by create_schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from arcane.infra.db.connection import Database
from arcane.infra.db.schema import RELATIONSHIP_REPAIR_KEY, create_schema
from tests.conftest import make_memory_dict


def _journey(db: Database, title: str = "J") -> str:
    now = datetime.now(timezone.utc).isoformat()
    journey_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO journeys (id, title, project, status, started_at, created_at, updated_at) "
        "VALUES (?, ?, 'p', 'active', ?, ?, ?)",
        (journey_id, title, now, now, now),
    )
    return journey_id


def _relationship(db: Database, source_id: str, target_id: str) -> str:
    rel_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relation, created_at) "
        "VALUES (?, 'memory', ?, 'journey', ?, 'part_of', ?)",
        (rel_id, source_id, target_id, datetime.now(timezone.utc).isoformat()),
    )
    return rel_id


class TestRelationshipIdRepair:
    def test_expands_unique_prefixes_and_leaves_the_rest(self, db, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem)
        journey_id = _journey(db)
        fixable = _relationship(db, mem["id"][:13], journey_id[:12])
        dangling = _relationship(db, mem["id"], "unknown")
        db.execute("DELETE FROM meta WHERE key = ?", (RELATIONSHIP_REPAIR_KEY,))
        db.commit()

        create_schema(db)

        rows = {r["id"]: r for r in db.fetchall("SELECT * FROM relationships")}
        assert (rows[fixable]["source_id"], rows[fixable]["target_id"]) == (mem["id"], journey_id)
        assert rows[dangling]["target_id"] == "unknown"

    def test_runs_once(self, db, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem)
        journey_id = _journey(db)
        rel = _relationship(db, mem["id"], journey_id[:12])
        db.commit()

        create_schema(db)  # repair flag already set by the fixture's create_schema

        row = db.fetchone("SELECT target_id FROM relationships WHERE id = ?", (rel,))
        assert row == {"target_id": journey_id[:12]}


class TestRenamedVecTableHeal:
    def test_restores_a_vec_table_broken_by_rename(self, db, memory_repo):
        db.execute(
            "CREATE VIRTUAL TABLE memories_vec_staging USING vec0(rowid INTEGER PRIMARY KEY, embedding float[2])"
        )
        db.execute("INSERT INTO memories_vec_staging (rowid, embedding) VALUES (1, ?)", ("[1, 2]",))
        db.execute("ALTER TABLE memories_vec_staging RENAME TO memories_vec")
        db.commit()

        create_schema(db)

        memory_repo.invalidate_vec_cache()
        assert memory_repo.get_vector(1) == [1.0, 2.0]
        memory_repo.insert_vector(2, [3.0, 4.0])
        assert memory_repo.get_vector(2) == [3.0, 4.0]


class TestJourneyFtsDeleteTrigger:
    def test_deleting_a_journey_keeps_its_fts_index_consistent(self, db, journey_repo):
        journey_repo.delete(_journey(db, title="Doomed journey"))

        db.execute("INSERT INTO journeys_fts(journeys_fts, rank) VALUES ('integrity-check', 1)")
        assert db.fetchall("SELECT rowid FROM journeys_fts WHERE journeys_fts MATCH 'doomed'") == []


class TestRedundantIndexes:
    def test_duplicate_indexes_are_dropped(self, db):
        db.execute("CREATE INDEX idx_mem_details_id ON memory_details(memory_id)")
        db.commit()

        create_schema(db)

        names = {r["name"] for r in db.fetchall("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "idx_mem_details_id" not in names
        assert "idx_artifacts_type_ext_proj" not in names
