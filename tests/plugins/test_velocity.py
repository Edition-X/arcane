"""Tests for the engineering velocity intelligence plugin."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from arcane.plugins.builtin.velocity import VelocityTracker


@pytest.fixture
def repos_with_data(artifact_repo, memory_repo, journey_repo):
    """Populate repos with commits, memories, and journeys over time."""
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)

    # Add commits spread over 3 weeks
    for i in range(15):
        day_offset = i * 1.5  # Every 1.5 days
        ts = (base + timedelta(days=day_offset)).isoformat()
        artifact_repo.insert({
            "id": str(uuid.uuid4()), "artifact_type": "commit",
            "external_id": f"sha-{i:03d}", "title": f"Commit {i}",
            "url": None, "project": "proj", "created_at": ts,
            "raw_data": {"files_changed": [f"file{i}.py"]},
        })

    # Add some memories
    for i in range(8):
        day_offset = i * 2.5
        ts = (base + timedelta(days=day_offset)).isoformat()
        memory_repo.insert({
            "id": str(uuid.uuid4()), "title": f"Memory {i}",
            "what": f"Learned thing {i}", "why": None, "impact": None,
            "tags": json.dumps(["test"]), "category": "learning",
            "project": "proj", "source": None, "related_files": json.dumps([]),
            "file_path": "/tmp/test.md", "section_anchor": f"mem-{i}",
            "created_at": ts, "updated_at": ts, "metadata": json.dumps({}),
        })

    # Add journeys
    for i in range(3):
        day_offset = i * 7
        ts = (base + timedelta(days=day_offset)).isoformat()
        journey_repo.insert({
            "id": str(uuid.uuid4()), "title": f"Journey {i}",
            "project": "proj", "status": "completed" if i < 2 else "active",
            "started_at": ts, "completed_at": ts if i < 2 else None,
            "summary": f"Summary {i}" if i < 2 else None,
            "linear_issue_id": None, "created_at": ts, "updated_at": ts,
        })

    return artifact_repo, memory_repo, journey_repo


class TestVelocityTracker:
    def test_implements_protocol(self):
        from arcane.plugins.protocols import IntelligencePlugin
        tracker = VelocityTracker(artifact_repo=None, memory_repo=None, journey_repo=None)
        assert isinstance(tracker, IntelligencePlugin)

    def test_name(self):
        tracker = VelocityTracker(artifact_repo=None, memory_repo=None, journey_repo=None)
        assert tracker.name == "velocity"

    def test_analyze_returns_insights(self, repos_with_data):
        artifact_repo, memory_repo, journey_repo = repos_with_data
        tracker = VelocityTracker(
            artifact_repo=artifact_repo,
            memory_repo=memory_repo,
            journey_repo=journey_repo,
        )
        insights = tracker.analyze(project="proj")

        assert len(insights) >= 1
        for insight in insights:
            assert insight["insight_type"] == "velocity"
            assert insight["project"] == "proj"
            assert "title" in insight
            assert "body" in insight

    def test_analyze_metadata_has_counts(self, repos_with_data):
        artifact_repo, memory_repo, journey_repo = repos_with_data
        tracker = VelocityTracker(
            artifact_repo=artifact_repo,
            memory_repo=memory_repo,
            journey_repo=journey_repo,
        )
        insights = tracker.analyze(project="proj")
        assert len(insights) >= 1

        meta = insights[0]["metadata"]
        assert "commit_count" in meta
        assert "memory_count" in meta
        assert "journey_count" in meta
        assert meta["commit_count"] == 15
        assert meta["memory_count"] == 8
        assert meta["journey_count"] == 3

    def test_analyze_empty_project(self, artifact_repo, memory_repo, journey_repo):
        tracker = VelocityTracker(
            artifact_repo=artifact_repo,
            memory_repo=memory_repo,
            journey_repo=journey_repo,
        )
        insights = tracker.analyze(project="nonexistent")
        # Should still return a summary, even if all zeros
        assert len(insights) >= 1
        meta = insights[0]["metadata"]
        assert meta["commit_count"] == 0
