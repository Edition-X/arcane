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


class TestServiceProjectCanonicalization:
    def test_save_canonicalizes_explicit_project(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="Canon Save", what="Body text")
        result = svc.save(raw, project="Edition X")

        assert container.memory_repo.get(result["id"])["project"] == "edition-x"

    def test_save_applies_alias(self, container):
        container.config.projects.aliases["grafana-usage-report"] = "grafana-usage-automation"
        svc = MemoryService(container)
        raw = RawMemoryInput(title="Alias Save", what="Body text")
        result = svc.save(raw, project="grafana-usage-report")

        assert container.memory_repo.get(result["id"])["project"] == "grafana-usage-automation"

    def test_save_preserves_empty_project_for_org_scope(self, container):
        svc = MemoryService(container)
        raw = RawMemoryInput(title="Org Level", what="Company-wide fact")
        result = svc.save(raw, project="", org="acme")

        assert container.memory_repo.get(result["id"])["project"] == ""

    def test_search_canonicalizes_project_filter(self, container):
        svc = MemoryService(container)
        svc.save(RawMemoryInput(title="Findable", what="UniqueCanonSearch"), project="edition-x")

        results = svc.search("UniqueCanonSearch", project="Edition X", use_vectors=False)
        assert any(r["title"] == "Findable" for r in results)

    def test_context_canonicalizes_project_filter(self, container):
        svc = MemoryService(container)
        svc.save(RawMemoryInput(title="Ctx Mem", what="Context body"), project="edition-x")

        results, total = svc.get_context(project="Edition X")
        assert total >= 1
        assert any(r["title"] == "Ctx Mem" for r in results)

    def test_journey_start_canonicalizes_project(self, container):
        js = JourneyService(container)
        j = js.start("Canon Journey", project="Edition X")
        assert j["project"] == "edition-x"

    def test_journey_start_applies_alias(self, container):
        container.config.projects.aliases["grafana-usage-report"] = "grafana-usage-automation"
        js = JourneyService(container)
        j = js.start("Alias Journey", project="grafana-usage-report")
        assert j["project"] == "grafana-usage-automation"


class _ConstantEmbedder:
    """Every text embeds to the same vector — everything is a perfect match."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        return [0.5] * self.dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class _BrokenEmbedder:
    """Embedding backend that is down."""

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")


class _TopicEmbedder:
    """Orthogonal vector per topic keyword — cosine 0 between topics.

    Vectors are deliberately unnormalised (norm 2.0) to mirror real backends
    like nomic-embed-text, so a check that relied on L2-derived scores would
    fail these tests.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        vec[0 if "pgbouncer" in text.lower() else 1] = 2.0
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class TestNearDuplicateDetection:
    def test_warns_on_semantically_close_memory(self, container):
        container._embedding_provider = _ConstantEmbedder()
        svc = MemoryService(container)

        first = svc.save(RawMemoryInput(title="Use pgbouncer for pooling", what="Connection pooling"), project="p")
        result = svc.save(
            RawMemoryInput(title="Adopt pgbouncer connection pool", what="Pool DB connections"), project="p"
        )

        assert result["action"] == "created"
        near = [w for w in result["warnings"] if "near_duplicate" in w]
        assert len(near) == 1
        assert first["id"] in near[0]
        assert "Use pgbouncer for pooling" in near[0]

    def test_save_is_never_blocked(self, container):
        container._embedding_provider = _ConstantEmbedder()
        svc = MemoryService(container)

        svc.save(RawMemoryInput(title="Original memory", what="Some body"), project="p")
        result = svc.save(RawMemoryInput(title="Paraphrased memory", what="Some text"), project="p")

        assert result["action"] == "created"
        assert container.memory_repo.get(result["id"]) is not None

    def test_no_warning_when_dissimilar(self, container):
        container._embedding_provider = _TopicEmbedder()
        svc = MemoryService(container)

        svc.save(RawMemoryInput(title="Use pgbouncer", what="Tuned pgbouncer pooling"), project="p")
        result = svc.save(RawMemoryInput(title="CI cache strategy", what="Cache node_modules"), project="p")

        assert not [w for w in result["warnings"] if "near_duplicate" in w]

    def test_warns_on_unnormalised_vectors(self, container):
        """Real backends return unnormalised vectors — similarity must be cosine-based."""
        container._embedding_provider = _TopicEmbedder()
        svc = MemoryService(container)

        first = svc.save(RawMemoryInput(title="Use pgbouncer for pooling", what="pgbouncer pools"), project="p")
        result = svc.save(RawMemoryInput(title="Adopt pgbouncer", what="pgbouncer for connections"), project="p")

        near = [w for w in result["warnings"] if "near_duplicate" in w]
        assert len(near) == 1
        assert first["id"] in near[0]

    def test_threshold_is_configurable(self, container):
        container._embedding_provider = _ConstantEmbedder()
        container.config.dedup.threshold = 1.01  # unreachable — disables the warning
        svc = MemoryService(container)

        svc.save(RawMemoryInput(title="First entry", what="Body one"), project="p")
        result = svc.save(RawMemoryInput(title="Second entry", what="Body two"), project="p")

        assert not [w for w in result["warnings"] if "near_duplicate" in w]

    def test_scoped_to_project_layer(self, container):
        container._embedding_provider = _ConstantEmbedder()
        svc = MemoryService(container)

        svc.save(RawMemoryInput(title="Other project memory", what="Body"), project="other")
        result = svc.save(RawMemoryInput(title="This project memory", what="Body"), project="p")

        assert not [w for w in result["warnings"] if "near_duplicate" in w]

    def test_broken_embeddings_fall_back_to_normalised_title(self, container):
        svc = MemoryService(container)
        svc.save(RawMemoryInput(title="fix auth bug", what="Race in token refresh"), project="p")

        container._embedding_provider = _BrokenEmbedder()
        result = svc.save(RawMemoryInput(title="Fix Auth Bug!", what="Different body entirely"), project="p")

        assert result["action"] == "created"
        assert [w for w in result["warnings"] if "near_duplicate" in w]

    def test_broken_embeddings_never_block_save(self, container):
        container._embedding_provider = _BrokenEmbedder()
        svc = MemoryService(container)

        result = svc.save(RawMemoryInput(title="Fresh memory", what="Body"), project="p")
        assert result["action"] == "created"
        assert not [w for w in result["warnings"] if "near_duplicate" in w]

    def test_org_level_save_does_not_match_project_memories(self, container):
        container._embedding_provider = _ConstantEmbedder()
        svc = MemoryService(container)

        svc.save(RawMemoryInput(title="Project fact", what="Body"), project="p", org="acme")
        result = svc.save(RawMemoryInput(title="Org-wide fact", what="Body"), project="", org="acme")

        assert not [w for w in result["warnings"] if "near_duplicate" in w]


class TestMemoryServiceUpdate:
    def test_update_fields(self, container):
        svc = MemoryService(container)
        r = svc.save(RawMemoryInput(title="Updatable", what="Old body"), project="p")

        ok = svc.update(r["id"], what="New body", why="New reason", tags=["fresh"])

        assert ok is True
        mem = container.memory_repo.get(r["id"])
        assert mem["what"] == "New body"
        assert mem["why"] == "New reason"
        assert mem["tags"] == ["fresh"]

    def test_update_reembeds(self, container, fake_embedder):
        svc = MemoryService(container)
        r = svc.save(RawMemoryInput(title="Reembed", what="Original"), project="p")
        calls_before = fake_embedder.call_count

        svc.update(r["id"], what="Changed content entirely")

        assert fake_embedder.call_count > calls_before

    def test_update_details_append(self, container):
        svc = MemoryService(container)
        r = svc.save(RawMemoryInput(title="With details", what="Body", details="First"), project="p")

        svc.update(r["id"], details_append="Second")

        detail = svc.get_details(r["id"])
        assert "First" in detail["body"]
        assert "Second" in detail["body"]

    def test_update_missing_returns_false(self, container):
        assert MemoryService(container).update("no-such-id", what="x") is False


class TestJourneyServiceLifecycle:
    def test_abandon(self, container):
        js = JourneyService(container)
        j = js.start("Doomed spike", project="p")

        assert js.abandon(j["id"], reason="superseded") is True
        got = js.get(j["id"])
        assert got["status"] == "abandoned"
        assert "superseded" in (got.get("summary") or "")

    def test_abandon_missing_returns_false(self, container):
        assert JourneyService(container).abandon("nope") is False

    def test_delete_removes_journey_and_relationships(self, container):
        js = JourneyService(container)
        j = js.start("Delete me", project="p")
        svc = MemoryService(container)
        m = svc.save(RawMemoryInput(title="Linked", what="Body", journey_id=j["id"]), project="p")

        assert js.delete(j["id"]) is True
        assert js.get(j["id"]) is None
        assert container.relationship_repo.get_all_for("journey", j["id"]) == []
        # The linked memory itself survives
        assert container.memory_repo.get(m["id"]) is not None
