"""Tests for the CI flake detection intelligence plugin."""

from __future__ import annotations

import uuid

import pytest

from arcane.plugins.builtin.ci_flakes import CIFlakeDetector


@pytest.fixture
def artifact_repo_with_runs(artifact_repo):
    """Populate artifact_repo with CI run artifacts, some flaky."""
    runs = [
        # Same commit, same branch, failure then success → flake
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-1",
            "title": "CI #1 [failure] on main",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-19T10:00:00+00:00",
            "raw_data": {
                "conclusion": "failure",
                "head_sha": "aaa",
                "head_branch": "main",
                "name": "CI",
                "run_attempt": 1,
                "event": "push",
            },
        },
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-2",
            "title": "CI #2 [success] on main",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-19T10:05:00+00:00",
            "raw_data": {
                "conclusion": "success",
                "head_sha": "aaa",
                "head_branch": "main",
                "name": "CI",
                "run_attempt": 2,
                "event": "push",
            },
        },
        # Different commit, consistent failure → NOT a flake
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-3",
            "title": "CI #3 [failure] on feature",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-20T10:00:00+00:00",
            "raw_data": {
                "conclusion": "failure",
                "head_sha": "bbb",
                "head_branch": "feature",
                "name": "CI",
                "run_attempt": 1,
                "event": "push",
            },
        },
        # Another flake pair on a different commit
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-4",
            "title": "CI #4 [failure] on main",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-20T12:00:00+00:00",
            "raw_data": {
                "conclusion": "failure",
                "head_sha": "ccc",
                "head_branch": "main",
                "name": "CI",
                "run_attempt": 1,
                "event": "push",
            },
        },
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-5",
            "title": "CI #5 [success] on main",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-20T12:05:00+00:00",
            "raw_data": {
                "conclusion": "success",
                "head_sha": "ccc",
                "head_branch": "main",
                "name": "CI",
                "run_attempt": 2,
                "event": "push",
            },
        },
        # Clean success
        {
            "id": str(uuid.uuid4()),
            "artifact_type": "ci_run",
            "external_id": "run-6",
            "title": "CI #6 [success] on main",
            "url": None,
            "project": "proj",
            "created_at": "2026-03-21T08:00:00+00:00",
            "raw_data": {
                "conclusion": "success",
                "head_sha": "ddd",
                "head_branch": "main",
                "name": "CI",
                "run_attempt": 1,
                "event": "push",
            },
        },
    ]
    for run in runs:
        artifact_repo.insert(run)
    return artifact_repo


class TestCIFlakeDetector:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import IntelligencePlugin

        detector = CIFlakeDetector(artifact_repo=None)
        assert isinstance(detector, IntelligencePlugin)

    def test_name(self):
        detector = CIFlakeDetector(artifact_repo=None)
        assert detector.name == "ci_flakes"

    def test_detects_flaky_runs(self, artifact_repo_with_runs):
        detector = CIFlakeDetector(artifact_repo=artifact_repo_with_runs)
        insights = detector.analyze(project="proj")

        # Should detect 2 flake pairs (aaa and ccc)
        assert len(insights) >= 1
        for insight in insights:
            assert insight["insight_type"] == "ci_flake"
            assert insight["project"] == "proj"
            assert "title" in insight
            assert "body" in insight
            assert "severity" in insight
            assert "metadata" in insight

    def test_flake_count_in_metadata(self, artifact_repo_with_runs):
        detector = CIFlakeDetector(artifact_repo=artifact_repo_with_runs)
        insights = detector.analyze(project="proj")
        # Should report the number of flaky commits
        assert len(insights) >= 1
        # The summary insight should have flake_count
        summary = insights[0]
        assert summary["metadata"].get("flake_count", 0) >= 2

    def test_no_flakes_returns_empty(self, artifact_repo):
        """No CI runs → no flakes."""
        detector = CIFlakeDetector(artifact_repo=artifact_repo)
        insights = detector.analyze(project="proj")
        assert insights == []

    def test_consistent_failures_not_flagged(self, artifact_repo):
        """Consistent failures (no retry success) are not flakes."""
        artifact_repo.insert(
            {
                "id": str(uuid.uuid4()),
                "artifact_type": "ci_run",
                "external_id": "run-solo",
                "title": "CI [failure]",
                "url": None,
                "project": "proj",
                "created_at": "2026-03-21T10:00:00+00:00",
                "raw_data": {
                    "conclusion": "failure",
                    "head_sha": "xxx",
                    "head_branch": "main",
                    "name": "CI",
                    "run_attempt": 1,
                    "event": "push",
                },
            }
        )
        detector = CIFlakeDetector(artifact_repo=artifact_repo)
        insights = detector.analyze(project="proj")
        assert insights == []
