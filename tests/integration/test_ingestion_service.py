"""Tests for the IngestionService that wires plugins to artifact storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from arcane.services.ingestion import IngestionService


class FakeIngestionPlugin:
    name = "fake"

    def __init__(self, results: list[dict[str, Any]] | None = None):
        self._results = results or []

    def ingest(self, project: str, since: datetime | None = None) -> list[dict[str, Any]]:
        return self._results

    def supports_incremental(self) -> bool:
        return True


def _make_artifact(title: str = "Test", ext_id: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "artifact_type": "commit",
        "external_id": ext_id or str(uuid.uuid4()),
        "title": title,
        "url": None,
        "project": "test-project",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw_data": {"key": "value"},
    }


class TestIngestionService:
    def test_run_plugin_stores_artifacts(self, container):
        artifacts = [_make_artifact("Commit 1"), _make_artifact("Commit 2")]
        plugin = FakeIngestionPlugin(results=artifacts)

        svc = IngestionService(container)
        result = svc.run_plugin(plugin, project="test-project")

        assert result["plugin"] == "fake"
        assert result["ingested"] == 2
        assert result["skipped"] == 0

        # Verify stored in DB
        stored = container.artifact_repo.list_all(project="test-project")
        assert len(stored) == 2

    def test_run_plugin_deduplicates(self, container):
        ext_id = "sha-123"
        artifacts = [_make_artifact("Commit", ext_id=ext_id)]
        plugin = FakeIngestionPlugin(results=artifacts)

        svc = IngestionService(container)
        # Run twice
        svc.run_plugin(plugin, project="test-project")
        result = svc.run_plugin(plugin, project="test-project")

        # Second run should skip the duplicate
        assert result["skipped"] == 1
        assert result["ingested"] == 0

        stored = container.artifact_repo.list_all(project="test-project")
        assert len(stored) == 1

    def test_run_plugin_with_since(self, container):
        artifacts = [_make_artifact("Recent")]
        plugin = FakeIngestionPlugin(results=artifacts)

        svc = IngestionService(container)
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = svc.run_plugin(plugin, project="test-project", since=since)

        assert result["ingested"] == 1

    def test_run_all_plugins(self, container):
        plugin1 = FakeIngestionPlugin(results=[_make_artifact("A")])
        plugin2 = FakeIngestionPlugin(results=[_make_artifact("B")])
        plugin2.name = "fake2"

        svc = IngestionService(container)
        results = svc.run_all([plugin1, plugin2], project="test-project")

        assert len(results) == 2
        assert sum(r["ingested"] for r in results) == 2

    def test_run_plugin_auto_links_to_journey(self, container):
        """If a journey_id is provided, link ingested artifacts."""
        from arcane.services.journey import JourneyService

        js = JourneyService(container)
        journey = js.start(title="Test Journey", project="test-project")

        artifacts = [_make_artifact("Commit for journey")]
        plugin = FakeIngestionPlugin(results=artifacts)

        svc = IngestionService(container)
        result = svc.run_plugin(plugin, project="test-project", journey_id=journey["id"])

        assert result["ingested"] == 1

        # Should have a relationship
        rels = container.relationship_repo.get_all_for("journey", journey["id"])
        assert len(rels) == 1
        assert rels[0]["relation"] == "part_of"
