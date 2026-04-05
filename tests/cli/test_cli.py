"""Tests for CLI commands."""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from arcane.cli import main

# All modules that import create_container from arcane.cli._utils.
# patch() must target where the name is *used*, not where it is defined.
_CLI_MODULES_WITH_CONTAINER = [
    "arcane.cli.memory",
    "arcane.cli.journey",
    "arcane.cli.analyze",
    "arcane.cli.ingest",
    "arcane.cli.relationship",
    "arcane.cli.draft",
]

_GET_HOME_PATCH = "arcane.cli.memory.get_home"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_container(container, tmp_home):
    """Mock create_container in all CLI modules to return our test container.

    We use a context manager stack to patch every module at once so a single
    fixture handles all command sub-modules cleanly.
    """
    container.close = lambda: None  # no-op — tests share the DB connection
    container.__enter__ = lambda s: s
    container.__exit__ = lambda s, *a: None

    with ExitStack() as stack:
        for module in _CLI_MODULES_WITH_CONTAINER:
            stack.enter_context(
                patch(f"{module}.create_container", return_value=container)
            )
        yield container


class TestStatsCLI:
    def test_stats_command(self, runner, mock_container):
        result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0, result.output
        assert "Memories:" in result.output
        assert "Journeys:" in result.output

    def test_stats_shows_zero_counts(self, runner, mock_container):
        result = runner.invoke(main, ["stats"])
        assert "0" in result.output


class TestInitCLI:
    def test_init_creates_vault(self, runner, tmp_path):
        home = str(tmp_path / "arcane-test")
        # get_home is called via a local import inside init(); target the source.
        with patch("arcane.infra.config.get_home", return_value=home):
            result = runner.invoke(main, ["init"])
        assert result.exit_code == 0, result.output
        assert os.path.isdir(os.path.join(home, "vault"))


class TestSearchCLI:
    def test_search_no_results(self, runner, mock_container):
        result = runner.invoke(main, ["search", "nonexistent"])
        assert result.exit_code == 0, result.output
        assert "No results" in result.output

    def test_search_with_results(self, runner, mock_container):
        from arcane.domain.models import RawMemoryInput
        from arcane.services.memory import MemoryService

        MemoryService(mock_container).save(
            RawMemoryInput(title="Test memory", what="Something useful"),
            project="test-project",
        )

        result = runner.invoke(main, ["search", "useful"])
        assert result.exit_code == 0, result.output
        assert "Test memory" in result.output


class TestJourneyCLI:
    def test_journey_start(self, runner, mock_container):
        result = runner.invoke(main, ["journey", "start", "--title", "Test Journey"])
        assert result.exit_code == 0, result.output
        assert "Journey started" in result.output

    def test_journey_list_empty(self, runner, mock_container):
        result = runner.invoke(main, ["journey", "list"])
        assert result.exit_code == 0, result.output
        assert "No journeys" in result.output

    def test_journey_lifecycle(self, runner, mock_container):
        # Start
        result = runner.invoke(main, ["journey", "start", "--title", "My Journey"])
        assert result.exit_code == 0, result.output
        journey_id = result.output.split("id: ")[1].strip().rstrip(")")

        # List
        result = runner.invoke(main, ["journey", "list"])
        assert "My Journey" in result.output

        # Complete
        result = runner.invoke(main, [
            "journey", "complete", journey_id, "--summary", "Done"
        ])
        assert result.exit_code == 0, result.output


class TestIngestCLI:
    def test_ingest_git_command_exists(self, runner, mock_container):
        result = runner.invoke(main, ["ingest", "--help"])
        assert result.exit_code == 0, result.output
        assert "git" in result.output

    def test_ingest_git_runs(self, runner, mock_container, tmp_path):
        """Ingest git in a non-git dir should report 0."""
        result = runner.invoke(main, ["ingest", "git", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "0" in result.output or "ingested" in result.output.lower()


class TestAnalyzeCLI:
    def test_analyze_command_exists(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0, result.output

    def test_analyze_flakes(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "flakes"])
        assert result.exit_code == 0, result.output

    def test_analyze_velocity(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "velocity"])
        assert result.exit_code == 0, result.output
