"""Integration tests for JourneyRepository."""

import uuid
from datetime import datetime, timezone

import pytest

from arcane.infra.db.ids import IdentifierResolutionError


def make_journey(**overrides) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "title": "Test Journey",
        "project": "test-project",
        "status": "active",
        "started_at": now,
        "completed_at": None,
        "summary": None,
        "linear_issue_id": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return defaults


class TestJourneyRepoInsert:
    def test_insert_and_get(self, journey_repo):
        j = make_journey(title="My Journey")
        journey_repo.insert(j)

        fetched = journey_repo.get(j["id"])
        assert fetched is not None
        assert fetched["title"] == "My Journey"
        assert fetched["status"] == "active"

    def test_get_by_prefix(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)

        prefix = j["id"][:8]
        fetched = journey_repo.get(prefix)
        assert fetched is not None
        assert fetched["id"] == j["id"]

    def test_count(self, journey_repo):
        assert journey_repo.count() == 0
        journey_repo.insert(make_journey(project="p1"))
        journey_repo.insert(make_journey(project="p2"))
        assert journey_repo.count() == 2
        assert journey_repo.count(project="p1") == 1


class TestJourneyRepoUpdate:
    def test_update(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)

        updated = journey_repo.update(j["id"], summary="In progress...")
        assert updated is True

        fetched = journey_repo.get(j["id"])
        assert fetched["summary"] == "In progress..."

    def test_update_nonexistent(self, journey_repo):
        assert journey_repo.update("nonexistent", summary="x") is False

    def test_complete(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)

        completed = journey_repo.complete(j["id"], summary="Done!")
        assert completed is True

        fetched = journey_repo.get(j["id"])
        assert fetched["status"] == "completed"
        assert fetched["completed_at"] is not None
        assert fetched["summary"] == "Done!"

    def test_events_preserve_updates_and_lifecycle(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)

        journey_repo.update(j["id"], summary="Investigating")
        journey_repo.complete(j["id"], summary="Resolved")

        events = journey_repo.list_events(j["id"])
        assert [(event["event_type"], event["summary"]) for event in events] == [
            ("updated", "Investigating"),
            ("completed", "Resolved"),
        ]

    def test_abandon_records_an_event(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)

        assert journey_repo.abandon(j["id"], reason="Superseded")

        assert [(event["event_type"], event["summary"]) for event in journey_repo.list_events(j["id"])] == [
            ("abandoned", "Abandoned: Superseded"),
        ]


class TestJourneyRepoList:
    def test_list_all(self, journey_repo):
        journey_repo.insert(make_journey(title="J1"))
        journey_repo.insert(make_journey(title="J2"))

        results = journey_repo.list_all()
        assert len(results) == 2

    def test_list_by_project(self, journey_repo):
        journey_repo.insert(make_journey(project="alpha"))
        journey_repo.insert(make_journey(project="beta"))

        results = journey_repo.list_all(project="alpha")
        assert len(results) == 1
        assert results[0]["project"] == "alpha"

    def test_list_by_status(self, journey_repo):
        j = make_journey()
        journey_repo.insert(j)
        journey_repo.complete(j["id"])

        active = journey_repo.list_all(status="active")
        completed = journey_repo.list_all(status="completed")
        assert len(active) == 0
        assert len(completed) == 1

    def test_list_limit(self, journey_repo):
        for i in range(10):
            journey_repo.insert(make_journey(title=f"J{i}"))

        results = journey_repo.list_all(limit=3)
        assert len(results) == 3


class TestJourneyRepoLifecycle:
    @staticmethod
    def _journey(journey_id, status="active", days_old=0, title="J", project="p"):
        from datetime import datetime, timedelta, timezone

        ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        return {
            "id": journey_id,
            "title": title,
            "project": project,
            "status": status,
            "started_at": ts,
            "created_at": ts,
            "updated_at": ts,
        }

    def test_list_stale_active(self, journey_repo):
        journey_repo.insert(self._journey("j-old", days_old=45))
        journey_repo.insert(self._journey("j-new", days_old=2))
        journey_repo.insert(self._journey("j-done", status="completed", days_old=90))

        stale = journey_repo.list_stale_active(days=30)

        assert [j["id"] for j in stale] == ["j-old"]

    def test_list_stale_active_project_filter(self, journey_repo):
        journey_repo.insert(self._journey("j-a", days_old=45, project="a"))
        journey_repo.insert(self._journey("j-b", days_old=45, project="b"))

        stale = journey_repo.list_stale_active(days=30, project="a")
        assert [j["id"] for j in stale] == ["j-a"]

    def test_list_stale_active_uses_updated_at_not_started_at(self, journey_repo):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()

        # Started 20 days ago but touched just now — not idle.
        journey_repo.insert(
            {
                "id": "j-recently-updated",
                "title": "Old start, fresh update",
                "project": "p",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": recent,
            }
        )
        # Started and last touched 20 days ago — idle.
        journey_repo.insert(
            {
                "id": "j-truly-stale",
                "title": "Old start, old update",
                "project": "p",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": old,
            }
        )

        stale = journey_repo.list_stale_active(days=14, project="p")

        assert [j["id"] for j in stale] == ["j-truly-stale"]

    def test_delete_by_id(self, journey_repo):
        journey_repo.insert(self._journey("j-doomed-123"))

        assert journey_repo.delete("j-doomed-123") is True
        assert journey_repo.get("j-doomed-123") is None

    def test_delete_by_prefix(self, journey_repo):
        journey_repo.insert(self._journey("j-doomed-456"))

        assert journey_repo.delete("j-doomed") is True
        assert journey_repo.get("j-doomed-456") is None

    def test_delete_missing_returns_false(self, journey_repo):
        with pytest.raises(IdentifierResolutionError, match="at least"):
            journey_repo.delete("nope")
