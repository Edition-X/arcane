"""MigrationService — migrate data from EchoVault to Arcane."""

from __future__ import annotations

import os
import shutil
from typing import Any

from arcane.infra.db.connection import Database
from arcane.infra.db.schema import create_schema


class MigrationService:
    """Handles migration from EchoVault to Arcane."""

    def migrate_from_echovault(
        self,
        source_home: str | None = None,
        target_home: str | None = None,
    ) -> dict[str, Any]:
        """Migrate EchoVault data to Arcane.

        Strategy: copy the database (schema is a superset), then run schema upgrade.
        """
        source_home = source_home or os.path.expanduser("~/.memory")
        from arcane.infra.config import get_home

        target_home = target_home or get_home()

        source_db = os.path.join(source_home, "index.db")
        source_vault = os.path.join(source_home, "vault")
        source_config = os.path.join(source_home, "config.yaml")
        source_ignore = os.path.join(source_home, ".memoryignore")

        target_db = os.path.join(target_home, "index.db")
        target_vault = os.path.join(target_home, "vault")
        target_config = os.path.join(target_home, "config.yaml")
        target_ignore = os.path.join(target_home, ".memoryignore")

        errors: list[str] = []

        if not os.path.exists(source_db):
            return {"success": False, "errors": [f"Source database not found: {source_db}"]}

        os.makedirs(target_home, exist_ok=True)

        # 1. Copy database
        if os.path.exists(target_db):
            errors.append(f"Target database already exists: {target_db} (skipping copy)")
        else:
            shutil.copy2(source_db, target_db)

        # 2. Run schema upgrade (additive — adds new tables, columns)
        db = Database(target_db)
        create_schema(db)

        # Count memories
        row = db.fetchone("SELECT COUNT(*) as cnt FROM memories")
        memory_count = row["cnt"] if row else 0
        db.close()

        # 3. Copy vault directory
        if os.path.exists(source_vault):
            if os.path.exists(target_vault):
                # Merge — copy files that don't exist in target
                for dirpath, _dirnames, filenames in os.walk(source_vault):
                    rel_dir = os.path.relpath(dirpath, source_vault)
                    target_dir = os.path.join(target_vault, rel_dir)
                    os.makedirs(target_dir, exist_ok=True)
                    for fname in filenames:
                        src_file = os.path.join(dirpath, fname)
                        tgt_file = os.path.join(target_dir, fname)
                        if not os.path.exists(tgt_file):
                            shutil.copy2(src_file, tgt_file)
            else:
                shutil.copytree(source_vault, target_vault)

        # 4. Copy config if not present
        if os.path.exists(source_config) and not os.path.exists(target_config):
            shutil.copy2(source_config, target_config)

        if os.path.exists(source_ignore) and not os.path.exists(target_ignore):
            shutil.copy2(source_ignore, target_ignore)

        return {
            "success": True,
            "memory_count": memory_count,
            "source": source_home,
            "target": target_home,
            "errors": errors,
        }

    def verify(self, home: str | None = None) -> dict[str, Any]:
        """Verify migration integrity."""
        from arcane.infra.config import get_home

        home = home or get_home()
        db_path = os.path.join(home, "index.db")

        if not os.path.exists(db_path):
            return {"success": False, "errors": ["Database not found"]}

        db = Database(db_path)
        checks: dict[str, Any] = {}

        # Count entities
        for table in ["memories", "journeys", "artifacts", "relationships", "insights"]:
            row = db.fetchone(f"SELECT COUNT(*) as cnt FROM {table}")
            checks[f"{table}_count"] = row["cnt"] if row else 0

        # Check FTS sync
        row = db.fetchone("SELECT COUNT(*) as cnt FROM memories_fts")
        fts_count = row["cnt"] if row else 0
        checks["fts_synced"] = fts_count == checks["memories_count"]

        # Check vec table
        row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='memories_vec'")
        checks["vec_table_exists"] = row is not None

        # Check embedding dim
        row = db.fetchone("SELECT value FROM meta WHERE key = 'embedding_dim'")
        checks["embedding_dim"] = int(row["value"]) if row else None

        db.close()

        checks["success"] = True
        return checks
