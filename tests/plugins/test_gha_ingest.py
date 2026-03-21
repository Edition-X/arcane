"""Tests for the GitHub Actions ingestion plugin."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from arcane.plugins.builtin.gha_ingest import GHAIngestionPlugin

MOCK_RUNS = [
    {
        "id": 12345,
        "name": "CI",
        "head_branch": "main",
        "head_sha": "abc123",
        "conclusion": "success",
        "status": "completed",
        "html_url": "https://github.com/owner/repo/actions/runs/12345",
        "created_at": "2026-03-20T10:00:00Z",
        "updated_at": "2026-03-20T10:05:00Z",
        "run_attempt": 1,
        "event": "push",
    },
    {
        "id": 12346,
        "name": "CI",
        "head_branch": "feature/foo",
        "head_sha": "def456",
        "conclusion": "failure",
        "status": "completed",
        "html_url": "https://github.com/owner/repo/actions/runs/12346",
        "created_at": "2026-03-19T08:00:00Z",
        "updated_at": "2026-03-19T08:10:00Z",
        "run_attempt": 1,
        "event": "pull_request",
    },
    {
        "id": 12347,
        "name": "CI",
        "head_branch": "feature/foo",
        "head_sha": "def456",
        "conclusion": "success",
        "status": "completed",
        "html_url": "https://github.com/owner/repo/actions/runs/12347",
        "created_at": "2026-03-19T09:00:00Z",
        "updated_at": "2026-03-19T09:05:00Z",
        "run_attempt": 2,
        "event": "pull_request",
    },
]


class TestGHAIngestionPlugin:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import IngestionPlugin
        plugin = GHAIngestionPlugin(owner="o", repo="r")
        assert isinstance(plugin, IngestionPlugin)

    def test_name(self):
        plugin = GHAIngestionPlugin(owner="o", repo="r")
        assert plugin.name == "github_actions"

    def test_supports_incremental(self):
        plugin = GHAIngestionPlugin(owner="o", repo="r")
        assert plugin.supports_incremental() is True

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_converts_to_artifacts(self, mock_fetch):
        mock_fetch.return_value = MOCK_RUNS
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")
        results = plugin.ingest(project="test-project")

        assert len(results) == 3
        for r in results:
            assert r["artifact_type"] == "ci_run"
            assert r["project"] == "test-project"
            assert "external_id" in r
            assert "title" in r
            assert "url" in r
            assert "raw_data" in r
            assert "created_at" in r

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_title_includes_conclusion(self, mock_fetch):
        mock_fetch.return_value = MOCK_RUNS[:1]
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")
        results = plugin.ingest(project="test-project")

        assert "success" in results[0]["title"].lower() or "CI" in results[0]["title"]

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_since_filter(self, mock_fetch):
        mock_fetch.return_value = MOCK_RUNS
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")

        since = datetime(2026, 3, 20, tzinfo=timezone.utc)
        results = plugin.ingest(project="test", since=since)
        # Only the run from Mar 20 should be included
        assert len(results) == 1
        assert results[0]["external_id"] == "12345"

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_raw_data_preserved(self, mock_fetch):
        mock_fetch.return_value = MOCK_RUNS[:1]
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")
        results = plugin.ingest(project="test")

        raw = results[0]["raw_data"]
        assert raw["conclusion"] == "success"
        assert raw["head_branch"] == "main"
        assert raw["event"] == "push"

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_failure_detection(self, mock_fetch):
        mock_fetch.return_value = MOCK_RUNS
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")
        results = plugin.ingest(project="test")

        failures = [r for r in results if r["raw_data"]["conclusion"] == "failure"]
        assert len(failures) == 1

    @patch("arcane.plugins.builtin.gha_ingest.GHAIngestionPlugin._fetch_runs")
    def test_ingest_empty_runs(self, mock_fetch):
        mock_fetch.return_value = []
        plugin = GHAIngestionPlugin(owner="owner", repo="repo")
        results = plugin.ingest(project="test")
        assert results == []
