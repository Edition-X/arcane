"""Tests for the Git ingestion plugin."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

import pytest

from arcane.plugins.builtin.git_ingest import GitIngestionPlugin


@pytest.fixture
def git_repo(tmp_path):
    """Create a real temporary git repo with commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, capture_output=True, env=env)

    # First commit
    (repo / "README.md").write_text("# Test Project")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True, env=env)

    # Second commit
    (repo / "src.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Add source file\n\nThis adds the main source."],
                   cwd=repo, capture_output=True, env=env)

    # Third commit
    (repo / "test.py").write_text("assert True")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Add tests"],
                   cwd=repo, capture_output=True, env=env)

    return str(repo)


class TestGitIngestionPlugin:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import IngestionPlugin
        plugin = GitIngestionPlugin()
        assert isinstance(plugin, IngestionPlugin)

    def test_name(self):
        plugin = GitIngestionPlugin()
        assert plugin.name == "git"

    def test_supports_incremental(self):
        plugin = GitIngestionPlugin()
        assert plugin.supports_incremental() is True

    def test_ingest_all_commits(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo)
        results = plugin.ingest(project="test-project")
        assert len(results) == 3
        # Most recent first
        assert results[0]["title"] == "Add tests"
        assert results[1]["title"] == "Add source file"
        assert results[2]["title"] == "Initial commit"

    def test_ingest_returns_artifact_dicts(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo)
        results = plugin.ingest(project="test-project")
        for r in results:
            assert "artifact_type" in r
            assert r["artifact_type"] == "commit"
            assert "external_id" in r
            assert "title" in r
            assert "project" in r
            assert "raw_data" in r
            assert "created_at" in r

    def test_ingest_raw_data_contains_details(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo)
        results = plugin.ingest(project="test-project")
        # The second commit has a body
        second = results[1]  # "Add source file"
        assert "author" in second["raw_data"]
        assert "files_changed" in second["raw_data"]
        assert "body" in second["raw_data"]
        assert second["raw_data"]["body"] == "This adds the main source."

    def test_ingest_since_filter(self, git_repo):
        """The since parameter should limit commits to those after the datetime."""
        plugin = GitIngestionPlugin(repo_path=git_repo)
        # Get all commits to find a timestamp
        all_commits = plugin.ingest(project="test-project")
        assert len(all_commits) >= 2

        # Use a since date that filters out some commits
        # Since all commits are recent, using "now" should return 0
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        results = plugin.ingest(project="test-project", since=future)
        assert len(results) == 0

    def test_ingest_with_max_count(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo, max_count=2)
        results = plugin.ingest(project="test-project")
        assert len(results) == 2

    def test_ingest_nonexistent_repo(self, tmp_path):
        plugin = GitIngestionPlugin(repo_path=str(tmp_path / "nope"))
        results = plugin.ingest(project="test-project")
        assert results == []

    def test_ingest_files_changed(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo)
        results = plugin.ingest(project="test-project")
        # "Add tests" commit should have test.py
        add_tests = results[0]
        assert "test.py" in add_tests["raw_data"]["files_changed"]

    def test_ingest_branch_info(self, git_repo):
        plugin = GitIngestionPlugin(repo_path=git_repo)
        results = plugin.ingest(project="test-project")
        # At least one result should have branch info
        assert all("branch" in r["raw_data"] for r in results)
