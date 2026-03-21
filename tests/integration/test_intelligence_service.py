"""Tests for the IntelligenceService that wires analysis plugins to insight storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from arcane.services.intelligence import IntelligenceService


class FakeAnalyzer:
    name = "fake_analyzer"

    def __init__(self, insights: list[dict[str, Any]] | None = None):
        self._insights = insights or []

    def analyze(self, project: str) -> list[dict[str, Any]]:
        return self._insights


def _make_insight(title: str = "Test Insight") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "insight_type": "test",
        "title": title,
        "body": "Test body",
        "severity": "info",
        "project": "test-project",
        "metadata": {"key": "value"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class TestIntelligenceService:
    def test_run_plugin_stores_insights(self, container):
        insights = [_make_insight("Finding 1"), _make_insight("Finding 2")]
        plugin = FakeAnalyzer(insights=insights)

        svc = IntelligenceService(container)
        result = svc.run_plugin(plugin, project="test-project")

        assert result["plugin"] == "fake_analyzer"
        assert result["insights_created"] == 2

        stored = container.insight_repo.list_all(project="test-project")
        assert len(stored) == 2

    def test_run_all_plugins(self, container):
        p1 = FakeAnalyzer(insights=[_make_insight("A")])
        p2 = FakeAnalyzer(insights=[_make_insight("B")])
        p2.name = "analyzer2"

        svc = IntelligenceService(container)
        results = svc.run_all([p1, p2], project="test-project")

        assert len(results) == 2
        assert sum(r["insights_created"] for r in results) == 2

    def test_run_plugin_empty_results(self, container):
        plugin = FakeAnalyzer(insights=[])

        svc = IntelligenceService(container)
        result = svc.run_plugin(plugin, project="test-project")

        assert result["insights_created"] == 0
