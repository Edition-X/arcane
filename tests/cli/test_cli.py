"""Tests for CLI commands."""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from arcane import __version__
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
            stack.enter_context(patch(f"{module}.create_container", return_value=container))
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


class TestVersionCLI:
    def test_version_command_reports_runtime_version(self, runner):
        result = runner.invoke(main, ["--version"])

        assert result.exit_code == 0, result.output
        assert __version__ in result.output


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
        result = runner.invoke(main, ["journey", "complete", journey_id, "--summary", "Done"])
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

    def test_analyze_velocity(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "velocity"])
        assert result.exit_code == 0, result.output


class TestProjectsCLI:
    def test_projects_lists_counts(self, runner, mock_container):
        from arcane.domain.models import RawMemoryInput
        from arcane.services.memory import MemoryService

        svc = MemoryService(mock_container)
        svc.save(RawMemoryInput(title="One", what="first"), project="proj-a")
        svc.save(RawMemoryInput(title="Two", what="second"), project="proj-a")
        svc.save(RawMemoryInput(title="Three", what="third"), project="proj-b")

        result = runner.invoke(main, ["projects"])
        assert result.exit_code == 0, result.output
        assert "proj-a" in result.output
        assert "proj-b" in result.output
        assert "2" in result.output

    def test_projects_empty(self, runner, mock_container):
        result = runner.invoke(main, ["projects"])
        assert result.exit_code == 0, result.output
        assert "No projects" in result.output


class TestMergeProjectsCLI:
    def _seed(self, container, project, title="Seed"):
        from arcane.domain.models import RawMemoryInput
        from arcane.services.memory import MemoryService

        MemoryService(container).save(RawMemoryInput(title=title, what="body"), project=project)

    def test_dry_run_by_default(self, runner, mock_container):
        self._seed(mock_container, "old-name")

        result = runner.invoke(main, ["merge-projects", "old-name", "new-name"])
        assert result.exit_code == 0, result.output
        assert "dry run" in result.output.lower()
        # Nothing moved
        rows = mock_container.memory_repo.list_projects()
        assert any(r["project"] == "old-name" for r in rows)
        assert not any(r["project"] == "new-name" for r in rows)

    def test_apply_moves_memories(self, runner, mock_container):
        self._seed(mock_container, "old-name", title="Moved A")
        self._seed(mock_container, "old-name", title="Moved B")

        result = runner.invoke(main, ["merge-projects", "old-name", "new-name", "--apply"])
        assert result.exit_code == 0, result.output
        assert "2" in result.output

        rows = mock_container.memory_repo.list_projects()
        assert not any(r["project"] == "old-name" for r in rows)
        assert any(r["project"] == "new-name" and r["cnt"] == 2 for r in rows)

    def test_destination_is_canonicalized(self, runner, mock_container):
        self._seed(mock_container, "old-name")

        result = runner.invoke(main, ["merge-projects", "old-name", "New Name", "--apply"])
        assert result.exit_code == 0, result.output
        rows = mock_container.memory_repo.list_projects()
        assert any(r["project"] == "new-name" for r in rows)

    def test_same_source_and_destination_errors(self, runner, mock_container):
        result = runner.invoke(main, ["merge-projects", "same-name", "Same Name"])
        assert result.exit_code != 0
        assert "same" in result.output.lower()

    def test_unknown_source_reports_zero(self, runner, mock_container):
        result = runner.invoke(main, ["merge-projects", "ghost", "new-name"])
        assert result.exit_code == 0, result.output
        assert "0" in result.output


class TestAnalyzeHealthCLI:
    def test_health_reports_findings(self, runner, mock_container):
        from tests.conftest import make_memory_dict

        mock_container.memory_repo.insert(make_memory_dict(project="Edition X"))
        mock_container.memory_repo.insert(make_memory_dict(project="edition-x"))

        result = runner.invoke(main, ["analyze", "health", "--project", "p"])
        assert result.exit_code == 0, result.output
        assert "fragmented" in result.output.lower()
        # Insights persisted for later `insights` calls
        stored = mock_container.insight_repo.list_all(project="p")
        assert any(i["insight_type"] == "health_fragmentation" for i in stored)

    def test_health_on_healthy_store(self, runner, mock_container):
        result = runner.invoke(main, ["analyze", "health", "--project", "p"])
        assert result.exit_code == 0, result.output
        assert "Health:" in result.output
