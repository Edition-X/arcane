"""Tests for the health audit intelligence plugin."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arcane.plugins.builtin.health_audit import HealthAuditor
from tests.conftest import make_memory_dict


@pytest.fixture
def auditor(memory_repo, journey_repo):
    return HealthAuditor(memory_repo=memory_repo, journey_repo=journey_repo)


def _insight_types(insights):
    return {i["insight_type"] for i in insights}


def _by_type(insights, insight_type):
    return [i for i in insights if i["insight_type"] == insight_type]


class TestHealthAuditorHealthyStore:
    def test_healthy_store_emits_single_info_summary(self, auditor, memory_repo):
        memory_repo.insert(make_memory_dict(title="A", project="proj-a"))
        memory_repo.insert(make_memory_dict(title="B", project="proj-a"))

        insights = auditor.analyze(project="proj-a")

        assert len(insights) == 1
        summary = insights[0]
        assert summary["insight_type"] == "health"
        assert summary["severity"] == "info"
        assert summary["project"] == "proj-a"

    def test_empty_store_does_not_crash(self, auditor):
        insights = auditor.analyze(project="proj-a")
        assert len(insights) == 1
        assert insights[0]["severity"] == "info"


class TestHealthAuditorFindings:
    def test_flags_project_fragmentation(self, auditor, memory_repo):
        memory_repo.insert(make_memory_dict(project="Edition X"))
        memory_repo.insert(make_memory_dict(project="edition-x"))

        insights = auditor.analyze(project="proj-a")

        frag = _by_type(insights, "health_fragmentation")
        assert len(frag) == 1
        assert frag[0]["severity"] == "warning"
        assert "Edition X" in frag[0]["body"]
        assert "edition-x" in frag[0]["body"]

    def test_fragmentation_respects_aliases(self, memory_repo, journey_repo):
        memory_repo.insert(make_memory_dict(project="grafana-usage-report"))
        memory_repo.insert(make_memory_dict(project="grafana-usage-automation"))

        auditor = HealthAuditor(
            memory_repo=memory_repo,
            journey_repo=journey_repo,
            aliases={"grafana-usage-report": "grafana-usage-automation"},
        )
        insights = auditor.analyze(project="proj-a")

        assert _by_type(insights, "health_fragmentation")

    def test_flags_empty_project_memories(self, auditor, memory_repo):
        memory_repo.insert(make_memory_dict(project=""))

        insights = auditor.analyze(project="proj-a")

        orphans = _by_type(insights, "health_empty_project")
        assert len(orphans) == 1
        assert orphans[0]["severity"] == "warning"

    def test_flags_duplicate_titles(self, auditor, memory_repo):
        memory_repo.insert(make_memory_dict(title="Same Title", project="proj-a"))
        memory_repo.insert(make_memory_dict(title="Same Title", project="proj-a"))

        insights = auditor.analyze(project="proj-a")

        dups = _by_type(insights, "health_duplicate_titles")
        assert len(dups) == 1
        assert dups[0]["severity"] == "warning"

    def test_flags_stale_active_journeys(self, auditor, journey_repo):
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        journey_repo.insert(
            {
                "id": "j-stale-1",
                "title": "Forgotten spike",
                "project": "proj-a",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": old,
            }
        )

        insights = auditor.analyze(project="proj-a")

        stale = _by_type(insights, "health_stale_journeys")
        assert len(stale) == 1
        assert stale[0]["severity"] == "warning"
        assert "Forgotten spike" in stale[0]["body"]

    def test_fresh_active_journey_not_flagged(self, auditor, journey_repo):
        now = datetime.now(timezone.utc).isoformat()
        journey_repo.insert(
            {
                "id": "j-fresh-1",
                "title": "Current work",
                "project": "proj-a",
                "status": "active",
                "started_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )

        insights = auditor.analyze(project="proj-a")
        assert not _by_type(insights, "health_stale_journeys")

    def test_summary_reports_adoption_metrics(self, auditor, memory_repo):
        memory_repo.insert(make_memory_dict(project="proj-a", ttl_days=30))
        memory_repo.insert(make_memory_dict(project="proj-a"))

        insights = auditor.analyze(project="proj-a")

        summary = _by_type(insights, "health")[0]
        assert "TTL" in summary["body"] or "ttl" in summary["body"]

    def test_plugin_name_is_health(self, auditor):
        assert auditor.name == "health"
