"""Tests for MCP tool handler functions."""

import json

import pytest

from arcane.mcp_server.tools.content_tools import handle_draft_adr, handle_draft_blog
from arcane.mcp_server.tools.intelligence_tools import handle_insights, handle_insights_ack
from arcane.mcp_server.tools.journey_tools import (
    handle_journey_complete,
    handle_journey_list,
    handle_journey_start,
    handle_journey_update,
)
from arcane.mcp_server.tools.memory_tools import (
    handle_context,
    handle_delete,
    handle_details,
    handle_save,
    handle_search,
)
from arcane.mcp_server.tools.relationship_tools import handle_link, handle_trace
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService


@pytest.fixture
def mem_svc(container):
    return MemoryService(container)


@pytest.fixture
def journey_svc(container):
    return JourneyService(container)


class TestMemoryToolHandlers:
    def test_handle_save(self, mem_svc):
        result = json.loads(handle_save(
            mem_svc,
            title="Handler Test",
            what="Testing the handler",
            project="test",
        ))
        assert result["action"] == "created"
        assert result["id"]

    def test_handle_save_with_category(self, mem_svc):
        result = json.loads(handle_save(
            mem_svc,
            title="Decision",
            what="Chose X",
            category="decision",
            project="test",
        ))
        assert result["action"] == "created"

    def test_handle_save_invalid_category(self, mem_svc):
        result = json.loads(handle_save(
            mem_svc,
            title="Bad Cat",
            what="Invalid category",
            category="invalid_cat",
            project="test",
        ))
        assert result["action"] == "created"

    def test_handle_search(self, mem_svc):
        handle_save(mem_svc, title="Searchable", what="Find me", project="test")
        result = json.loads(handle_search(mem_svc, query="Searchable"))
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["title"] == "Searchable"

    def test_handle_search_empty(self, mem_svc):
        result = json.loads(handle_search(mem_svc, query="nonexistent xyz"))
        assert result == []

    def test_handle_context(self, mem_svc):
        handle_save(mem_svc, title="Ctx Test", what="Context item", project="test")
        result = json.loads(handle_context(mem_svc, project="test"))
        assert result["total"] >= 1
        assert len(result["memories"]) >= 1

    def test_handle_details(self, mem_svc):
        saved = json.loads(handle_save(
            mem_svc,
            title="Detail Test",
            what="Has details",
            details="Full body content",
            project="test",
        ))
        result = json.loads(handle_details(mem_svc, memory_id=saved["id"]))
        assert result["body"] == "Full body content"

    def test_handle_details_not_found(self, mem_svc):
        result = json.loads(handle_details(mem_svc, memory_id="nonexistent"))
        assert "error" in result

    def test_handle_delete(self, mem_svc):
        saved = json.loads(handle_save(mem_svc, title="Delete Me", what="Bye", project="test"))
        result = json.loads(handle_delete(mem_svc, memory_id=saved["id"]))
        assert result["deleted"] is True


class TestJourneyToolHandlers:
    def test_handle_journey_start(self, journey_svc):
        result = json.loads(handle_journey_start(journey_svc, title="New Journey", project="test"))
        assert result["id"]
        assert result["title"] == "New Journey"

    def test_handle_journey_update(self, journey_svc):
        j = json.loads(handle_journey_start(journey_svc, title="J", project="test"))
        result = json.loads(handle_journey_update(journey_svc, journey_id=j["id"], summary="Updated"))
        assert result["updated"] is True

    def test_handle_journey_complete(self, journey_svc):
        j = json.loads(handle_journey_start(journey_svc, title="J", project="test"))
        result = json.loads(handle_journey_complete(journey_svc, journey_id=j["id"], summary="Done"))
        assert result["completed"] is True

    def test_handle_journey_list(self, journey_svc):
        handle_journey_start(journey_svc, title="J1", project="test")
        handle_journey_start(journey_svc, title="J2", project="test")
        result = json.loads(handle_journey_list(journey_svc, project="test"))
        assert len(result) == 2


class TestRelationshipToolHandlers:
    def test_handle_link(self, container):
        result = json.loads(handle_link(
            container,
            source_type="memory",
            source_id="m1",
            target_type="journey",
            target_id="j1",
            relation="part_of",
        ))
        assert result["created"] is True
        assert result["id"]

    def test_handle_link_invalid_type(self, container):
        result = json.loads(handle_link(
            container,
            source_type="invalid",
            source_id="m1",
            target_type="journey",
            target_id="j1",
            relation="part_of",
        ))
        assert "error" in result

    def test_handle_link_invalid_relation(self, container):
        result = json.loads(handle_link(
            container,
            source_type="memory",
            source_id="m1",
            target_type="journey",
            target_id="j1",
            relation="bad_relation",
        ))
        assert "error" in result

    def test_handle_trace(self, container):
        handle_link(
            container,
            source_type="memory", source_id="m1",
            target_type="journey", target_id="j1",
            relation="part_of",
        )
        result = json.loads(handle_trace(container, entity_type="memory", entity_id="m1"))
        assert isinstance(result, list)
        assert len(result) == 1


class TestIntelligenceToolHandlers:
    def test_handle_insights_empty(self, container):
        result = json.loads(handle_insights(container, project="test"))
        assert result == []

    def test_handle_insights_with_data(self, container):
        from arcane.domain.models import Insight

        insight = Insight(
            insight_type="ci_flake",
            title="Flaky test detected",
            body="test_foo fails 30% of the time",
            project="test",
        )
        container.insight_repo.insert(insight.model_dump())

        result = json.loads(handle_insights(container, project="test"))
        assert len(result) == 1
        assert result[0]["title"] == "Flaky test detected"

    def test_handle_insights_ack(self, container):
        from arcane.domain.models import Insight

        insight = Insight(
            insight_type="ci_flake",
            title="Flaky",
            body="Details",
            project="test",
        )
        container.insight_repo.insert(insight.model_dump())

        result = json.loads(handle_insights_ack(container, insight_id=insight.id))
        assert result["acknowledged"] is True

        # Should be empty after acknowledging
        remaining = json.loads(handle_insights(container, project="test"))
        assert len(remaining) == 0


class TestIngestionToolHandlers:
    def test_handle_ingest_git_empty_repo(self, container, tmp_path):
        from arcane.mcp_server.tools.ingestion_tools import handle_ingest_git
        result = json.loads(handle_ingest_git(container, project="test", repo_path=str(tmp_path)))
        assert result["plugin"] == "git"
        assert result["ingested"] == 0

    def test_handle_analyze_velocity(self, container):
        from arcane.mcp_server.tools.ingestion_tools import handle_analyze
        result = json.loads(handle_analyze(container, plugin_name="velocity", project="test"))
        assert result["plugin"] == "velocity"
        assert result["insights_created"] >= 1

    def test_handle_analyze_unknown(self, container):
        from arcane.mcp_server.tools.ingestion_tools import handle_analyze
        result = json.loads(handle_analyze(container, plugin_name="unknown"))
        assert "error" in result


class TestContentToolHandlers:
    def test_handle_draft_adr(self, container):
        from tests.conftest import make_memory_dict

        mem = make_memory_dict(title="Use SQLite", what="We chose SQLite", why="Simplicity")
        container.memory_repo.insert(mem, details="Full ADR body here")

        result = json.loads(handle_draft_adr(container, memory_id=mem["id"]))
        assert "brief" in result
        assert "Use SQLite" in result["brief"]
        assert "Simplicity" in result["brief"]

    def test_handle_draft_adr_not_found(self, container):
        result = json.loads(handle_draft_adr(container, memory_id="nonexistent"))
        assert "error" in result

    def test_handle_draft_blog_no_journey(self, container):
        result = json.loads(handle_draft_blog(container))
        assert "error" in result
