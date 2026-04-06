"""Tests for the Linear ingestion plugin."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from arcane.plugins.builtin.linear_ingest import LinearIngestionPlugin

MOCK_ISSUES = [
    {
        "id": "issue-1",
        "identifier": "PROJ-101",
        "title": "Fix authentication flow",
        "state": {"name": "Done"},
        "url": "https://linear.app/team/issue/PROJ-101",
        "createdAt": "2026-03-15T10:00:00.000Z",
        "updatedAt": "2026-03-20T14:00:00.000Z",
        "description": "The auth flow breaks when...",
        "labels": {"nodes": [{"name": "bug"}, {"name": "auth"}]},
        "assignee": {"name": "Dan"},
        "priority": 2,
        "estimate": 3,
    },
    {
        "id": "issue-2",
        "identifier": "PROJ-102",
        "title": "Add caching layer",
        "state": {"name": "In Progress"},
        "url": "https://linear.app/team/issue/PROJ-102",
        "createdAt": "2026-03-18T10:00:00.000Z",
        "updatedAt": "2026-03-21T10:00:00.000Z",
        "description": "We need a caching layer for...",
        "labels": {"nodes": [{"name": "enhancement"}]},
        "assignee": {"name": "Dan"},
        "priority": 1,
        "estimate": 5,
    },
]

# Convenience patch decorator targeting the paginated method name.
_PATCH_FETCH = "arcane.plugins.builtin.linear_ingest.LinearIngestionPlugin._fetch_all_issues"


class TestLinearIngestionPlugin:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import IngestionPlugin

        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        assert isinstance(plugin, IngestionPlugin)

    def test_name(self):
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        assert plugin.name == "linear"

    def test_supports_incremental(self):
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        assert plugin.supports_incremental() is True

    @patch(_PATCH_FETCH)
    def test_ingest_converts_to_artifacts(self, mock_fetch):
        mock_fetch.return_value = MOCK_ISSUES
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        results = plugin.ingest(project="test-project")

        assert len(results) == 2
        for r in results:
            assert r["artifact_type"] == "linear_ticket"
            assert r["project"] == "test-project"
            assert "external_id" in r
            assert "title" in r
            assert "url" in r
            assert "raw_data" in r
            assert "created_at" in r

    @patch(_PATCH_FETCH)
    def test_ingest_external_id_uses_identifier(self, mock_fetch):
        mock_fetch.return_value = MOCK_ISSUES[:1]
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        results = plugin.ingest(project="test")
        assert results[0]["external_id"] == "PROJ-101"

    @patch(_PATCH_FETCH)
    def test_ingest_raw_data_includes_labels(self, mock_fetch):
        mock_fetch.return_value = MOCK_ISSUES[:1]
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        results = plugin.ingest(project="test")
        assert results[0]["raw_data"]["labels"] == ["bug", "auth"]

    @patch(_PATCH_FETCH)
    def test_ingest_since_filter(self, mock_fetch):
        mock_fetch.return_value = MOCK_ISSUES
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")

        since = datetime(2026, 3, 17, tzinfo=timezone.utc)
        results = plugin.ingest(project="test", since=since)
        # Only issue-2 was created after Mar 17
        assert len(results) == 1
        assert results[0]["external_id"] == "PROJ-102"

    @patch(_PATCH_FETCH)
    def test_ingest_empty(self, mock_fetch):
        mock_fetch.return_value = []
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        results = plugin.ingest(project="test")
        assert results == []

    @patch(_PATCH_FETCH)
    def test_ingest_state_preserved(self, mock_fetch):
        mock_fetch.return_value = MOCK_ISSUES
        plugin = LinearIngestionPlugin(api_key="test-key", team_id="PROJ")
        results = plugin.ingest(project="test")
        assert results[0]["raw_data"]["state"] == "Done"
        assert results[1]["raw_data"]["state"] == "In Progress"
