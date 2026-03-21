"""Tests for CLI commands."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from arcane.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_container(container, tmp_home):
    """Mock create_container to return our test container.

    We also patch container.close() to be a no-op so sequential CLI
    invocations in the same test don't close the underlying DB.
    """
    container.close = lambda: None  # no-op for tests
    with patch("arcane.cli.create_container", return_value=container):
        yield container


class TestStatsCLI:
    def test_stats_command(self, runner, mock_container):
        result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0
        assert "Memories:" in result.output
        assert "Journeys:" in result.output

    def test_stats_shows_zero_counts(self, runner, mock_container):
        result = runner.invoke(main, ["stats"])
        assert "0" in result.output


class TestInitCLI:
    def test_init_creates_vault(self, runner, tmp_path):
        home = str(tmp_path / "arcane-test")
        with patch("arcane.cli.get_home", return_value=home):
            result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert os.path.isdir(os.path.join(home, "vault"))


class TestSearchCLI:
    def test_search_no_results(self, runner, mock_container):
        result = runner.invoke(main, ["search", "nonexistent"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_with_results(self, runner, mock_container):
        from arcane.domain.models import RawMemoryInput
        from arcane.services.memory import MemoryService

        svc = MemoryService(mock_container)
        svc.save(
            RawMemoryInput(title="Test memory", what="Something useful"),
            project="test-project",
        )

        result = runner.invoke(main, ["search", "useful"])
        assert result.exit_code == 0
        assert "Test memory" in result.output


class TestJourneyCLI:
    def test_journey_start(self, runner, mock_container):
        result = runner.invoke(main, ["journey", "start", "--title", "Test Journey"])
        assert result.exit_code == 0
        assert "Journey started" in result.output

    def test_journey_list_empty(self, runner, mock_container):
        result = runner.invoke(main, ["journey", "list"])
        assert result.exit_code == 0
        assert "No journeys" in result.output

    def test_journey_lifecycle(self, runner, mock_container):
        # Start
        result = runner.invoke(main, ["journey", "start", "--title", "My Journey"])
        assert result.exit_code == 0
        # Extract journey ID from output
        journey_id = result.output.split("id: ")[1].strip().rstrip(")")

        # List
        result = runner.invoke(main, ["journey", "list"])
        assert "My Journey" in result.output

        # Complete
        result = runner.invoke(main, [
            "journey", "complete", journey_id, "--summary", "Done"
        ])
        assert result.exit_code == 0


class TestIngestCLI:
    def test_ingest_git_command_exists(self, runner, mock_container):
        result = runner.invoke(main, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "git" in result.output

    def test_ingest_git_runs(self, runner, mock_container, tmp_path):
        """Ingest git in a non-git dir should report 0."""
        result = runner.invoke(main, ["ingest", "git", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "0" in result.output or "ingested" in result.output.lower()


class TestAnalyzeCLI:
    def test_analyze_command_exists(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_analyze_flakes(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "flakes"])
        assert result.exit_code == 0

    def test_analyze_velocity(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "velocity"])
        assert result.exit_code == 0
