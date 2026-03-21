"""Integration tests for JourneyRepository."""

import uuid
from datetime import datetime, timezone


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
