"""Integration tests for MemoryService and JourneyService."""

import os

from arcane.domain.models import RawMemoryInput
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService


class TestMemoryServiceSave:
    def test_save_new_memory(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="New Decision", what="We chose SQLite", category="decision")
        result = svc.save(raw, project="arcane")

        assert result["action"] == "created"
        assert result["id"]
        assert result["file_path"]

    def test_save_creates_vault_file(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="Vault Test", what="Check file creation")
        result = svc.save(raw, project="test-proj")

        assert os.path.exists(result["file_path"])

    def test_save_dedup_updates_existing(self, container):
        svc = MemoryService(container)

        raw1 = RawMemoryInput(title="Duplicate Title", what="First version")
        r1 = svc.save(raw1, project="p")
        assert r1["action"] == "created"

        raw2 = RawMemoryInput(title="Duplicate Title", what="Second version")
        r2 = svc.save(raw2, project="p")
        assert r2["action"] == "updated"
        assert r2["id"] == r1["id"]

    def test_save_redacts_secrets(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(
            title="Secret Test",
            what="Key is sk_live_abc123xyz",
        )
        svc.save(raw, project="p")

        mem = container.memory_repo.fts_search("Secret Test")
        assert len(mem) >= 1
        assert "sk_live_abc123xyz" not in mem[0]["what"]
        assert "[REDACTED]" in mem[0]["what"]

    def test_save_with_journey_creates_link(self, container):
        js = JourneyService(container)
        j = js.start("Test Journey", project="p")

        svc = MemoryService(container)
        raw = RawMemoryInput(title="Linked Mem", what="Part of journey", journey_id=j["id"])
        result = svc.save(raw, project="p")

        rels = container.relationship_repo.get_all_for("memory", result["id"])
        assert len(rels) == 1
        assert rels[0]["target_id"] == j["id"]
        assert rels[0]["relation"] == "part_of"

    def test_save_with_details(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(
            title="Detailed Decision",
            what="Chose approach A",
            details="Context: blah\nOptions considered: A, B\nDecision: A\nTradeoffs: none\nFollow-up: monitor",
        )
        result = svc.save(raw, project="p")

        detail = svc.get_details(result["id"])
        assert detail is not None
        assert "Context: blah" in detail["body"]


class TestMemoryServiceSearch:
    def test_search_finds_memory(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="Terraform AMI", what="Built AMI pipeline for fleet")
        svc.save(raw, project="infra")

        results = svc.search("terraform AMI", project="infra")
        assert len(results) >= 1
        assert "Terraform" in results[0]["title"]

    def test_search_empty_result(self, container):
        svc = MemoryService(container)
        results = svc.search("nonexistent gibberish xyz")
        assert results == []


class TestMemoryServiceContext:
    def test_get_context(self, container):
        svc = MemoryService(container)
        for i in range(5):
            svc.save(RawMemoryInput(title=f"Ctx {i}", what=f"Item {i}"), project="p")

        results, total = svc.get_context(limit=3, project="p")
        assert total == 5
        assert len(results) == 3


class TestMemoryServiceDelete:
    def test_delete(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="To Delete", what="Bye")
        result = svc.save(raw, project="p")

        assert svc.delete(result["id"]) is True
        assert container.memory_repo.get(result["id"]) is None


class TestJourneyServiceIntegration:
    def test_full_lifecycle(self, container):
        svc = JourneyService(container)

        # Start
        j = svc.start("CI Reliability", project="infra")
        assert j["id"]
        assert j["project"] == "infra"

        # Update
        assert svc.update(j["id"], summary="Investigating flakes") is True

        # Complete
        assert svc.complete(j["id"], summary="Resolved: larger runners") is True

        # Verify
        fetched = svc.get(j["id"])
        assert fetched["status"] == "completed"
        assert fetched["summary"] == "Resolved: larger runners"

    def test_list(self, container):
        svc = JourneyService(container)
        svc.start("J1", project="p")
        svc.start("J2", project="p")

        journeys = svc.list(project="p")
        assert len(journeys) == 2

    def test_show_with_linked_entities(self, container):
        svc = JourneyService(container)
        j = svc.start("Show Test", project="p")

        # Link a memory
        mem_svc = MemoryService(container)
        raw = RawMemoryInput(title="Linked", what="Part of journey", journey_id=j["id"])
        mem_svc.save(raw, project="p")

        shown = svc.show(j["id"])
        assert shown is not None
        assert len(shown["linked_memories"]) == 1
        assert shown["linked_memories"][0]["relation"] == "part_of"

    def test_link_memory(self, container):
        svc = JourneyService(container)
        j = svc.start("Link Test", project="p")

        mem_svc = MemoryService(container)
        raw = RawMemoryInput(title="Manual Link", what="Linked manually")
        mem_result = mem_svc.save(raw, project="p")

        rel_id = svc.link_memory(j["id"], mem_result["id"])
        assert rel_id

        rels = container.relationship_repo.get_all_for("journey", j["id"])
        assert len(rels) == 1
