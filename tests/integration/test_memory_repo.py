"""Integration tests for MemoryRepository with real SQLite."""

import json

from tests.conftest import make_memory_dict


class TestMemoryRepoInsert:
    def test_insert_and_get(self, memory_repo):
        mem = make_memory_dict(title="Test Insert", what="Testing insert")
        rowid = memory_repo.insert(mem)
        assert rowid > 0

        fetched = memory_repo.get(mem["id"])
        assert fetched is not None
        assert fetched["title"] == "Test Insert"
        assert fetched["what"] == "Testing insert"

    def test_insert_with_details(self, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem, details="Full body here")

        detail = memory_repo.get_details(mem["id"])
        assert detail is not None
        assert detail["body"] == "Full body here"

    def test_count(self, memory_repo):
        assert memory_repo.count() == 0
        memory_repo.insert(make_memory_dict(project="p1"))
        memory_repo.insert(make_memory_dict(project="p2"))
        assert memory_repo.count() == 2
        assert memory_repo.count(project="p1") == 1


class TestMemoryRepoUpdate:
    def test_update_fields(self, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem)

        updated = memory_repo.update(mem["id"], what="Updated what", tags=["new-tag"])
        assert updated is True

        fetched = memory_repo.get(mem["id"])
        assert fetched["what"] == "Updated what"
        assert json.loads(fetched["tags"]) == ["new-tag"]

    def test_update_nonexistent(self, memory_repo):
        assert memory_repo.update("nonexistent-id", what="x") is False

    def test_update_appends_details(self, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem, details="Original")
        memory_repo.update(mem["id"], details_append="Appended")

        detail = memory_repo.get_details(mem["id"])
        assert "Original" in detail["body"]
        assert "Appended" in detail["body"]

    def test_update_creates_details_if_missing(self, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem)  # no details
        memory_repo.update(mem["id"], details_append="New details")

        detail = memory_repo.get_details(mem["id"])
        assert detail["body"] == "New details"


class TestMemoryRepoDelete:
    def test_delete(self, memory_repo):
        mem = make_memory_dict()
        memory_repo.insert(mem, details="To be deleted")

        assert memory_repo.delete(mem["id"]) is True
        assert memory_repo.get(mem["id"]) is None
        assert memory_repo.get_details(mem["id"]) is None

    def test_delete_nonexistent(self, memory_repo):
        assert memory_repo.delete("nonexistent") is False


class TestMemoryRepoFTSSearch:
    def test_fts_finds_by_title(self, memory_repo):
        mem = make_memory_dict(title="Terraform AMI pipeline", what="Built a pipeline")
        memory_repo.insert(mem)

        results = memory_repo.fts_search("terraform")
        assert len(results) >= 1
        assert results[0]["title"] == "Terraform AMI pipeline"

    def test_fts_finds_by_what(self, memory_repo):
        mem = make_memory_dict(title="Bug fix", what="Fixed the Kubernetes OOM issue")
        memory_repo.insert(mem)

        results = memory_repo.fts_search("kubernetes OOM")
        assert len(results) >= 1

    def test_fts_respects_project_filter(self, memory_repo):
        memory_repo.insert(make_memory_dict(title="A", what="shared", project="p1"))
        memory_repo.insert(make_memory_dict(title="B", what="shared", project="p2"))

        results = memory_repo.fts_search("shared", project="p1")
        assert all(r["project"] == "p1" for r in results)

    def test_fts_limit(self, memory_repo):
        for i in range(10):
            memory_repo.insert(make_memory_dict(title=f"Memory {i}", what="common term"))

        results = memory_repo.fts_search("common", limit=3)
        assert len(results) <= 3


class TestMemoryRepoListRecent:
    def test_list_recent(self, memory_repo):
        for i in range(5):
            memory_repo.insert(make_memory_dict(title=f"Mem {i}"))

        results = memory_repo.list_recent(limit=3)
        assert len(results) == 3

    def test_list_recent_project_filter(self, memory_repo):
        memory_repo.insert(make_memory_dict(project="alpha"))
        memory_repo.insert(make_memory_dict(project="beta"))

        results = memory_repo.list_recent(project="alpha")
        assert len(results) == 1


class TestMemoryRepoMeta:
    def test_set_and_get_meta(self, memory_repo):
        memory_repo.set_meta("test_key", "test_value")
        assert memory_repo.get_meta("test_key") == "test_value"

    def test_get_meta_missing(self, memory_repo):
        assert memory_repo.get_meta("nonexistent") is None

    def test_embedding_dim(self, memory_repo):
        assert memory_repo.get_embedding_dim() is None
        memory_repo.set_embedding_dim(768)
        assert memory_repo.get_embedding_dim() == 768
