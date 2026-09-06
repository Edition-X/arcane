"""Tests for MCP tool handler functions."""

import asyncio
import json

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from arcane import __version__
from arcane.mcp_server.server import _create_server
from arcane.mcp_server.tools.artifact_tools import handle_artifact_details, handle_artifact_search
from arcane.mcp_server.tools.content_tools import handle_draft_adr, handle_draft_blog
from arcane.mcp_server.tools.intelligence_tools import handle_insights, handle_insights_ack
from arcane.mcp_server.tools.journey_tools import (
    handle_journey_complete,
    handle_journey_list,
    handle_journey_show,
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


@pytest.fixture(autouse=True)
def _full_tool_profile(monkeypatch):
    """This module tests tool handlers, so it should see every tool.

    Without this, ARCANE_TOOL_PROFILE defaults to "core" and call_tool
    gates non-core tools before the handler ever runs, which silently
    turns "not found" assertions into "not enabled" assertions instead.
    Individual tests (e.g. tests/mcp/test_tool_profiles.py) that set the
    env var themselves still control it: monkeypatch calls made inside a
    test run after this fixture's, so they override it for that test.
    """
    monkeypatch.setenv("ARCANE_TOOL_PROFILE", "full")


@pytest.fixture
def mem_svc(container):
    return MemoryService(container)


@pytest.fixture
def journey_svc(container):
    return JourneyService(container)


class TestMemoryToolHandlers:
    def test_handle_save(self, mem_svc):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Handler Test",
                what="Testing the handler",
                project="test",
            )
        )
        assert result["action"] == "created"
        assert result["id"]

    def test_handle_save_with_category(self, mem_svc):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Decision",
                what="Chose X",
                category="decision",
                project="test",
            )
        )
        assert result["action"] == "created"

    def test_handle_save_stores_explicit_source(self, mem_svc, container):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Sourced",
                what="Came from codex",
                project="test",
                source="codex",
            )
        )
        mem = container.memory_repo.get(result["id"])
        assert mem["source"] == "codex"

    def test_handle_save_without_source_is_unset(self, mem_svc, container):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Unsourced",
                what="No source given",
                project="test",
            )
        )
        mem = container.memory_repo.get(result["id"])
        assert not mem["source"]

    def test_handle_save_collapses_worktree_project_variant(self, mem_svc, monkeypatch):
        from arcane.domain.scope import Scope

        monkeypatch.setattr(
            "arcane.domain.scope.resolve_scope",
            lambda cwd, config, _remote=None: Scope(org="personal", project="repo"),
        )
        result = json.loads(
            handle_save(
                mem_svc,
                title="Worktree Save",
                what="Saved from a worktree checkout",
                project="repo-inf999",
            )
        )
        assert result["action"] == "created"
        assert result["scope"]["project"] == "repo-inf999"

        found = json.loads(handle_search(mem_svc, query="Worktree Save", project="repo"))
        assert any(m["id"] == result["id"] for m in found)

    def test_handle_save_invalid_category(self, mem_svc):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Bad Cat",
                what="Invalid category",
                category="invalid_cat",
                project="test",
            )
        )
        assert result["action"] == "created"

    def test_handle_search(self, mem_svc):
        handle_save(mem_svc, title="Searchable", what="Find me", project="test")
        result = json.loads(handle_search(mem_svc, query="Searchable", project="test"))
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["title"] == "Searchable"

    def test_handle_search_empty(self, mem_svc):
        result = json.loads(handle_search(mem_svc, query="nonexistent xyz"))
        assert result == []

    def test_handle_search_none_limit_uses_default(self, mem_svc):
        handle_save(mem_svc, title="Searchable with None limit", what="Find me", project="test")
        result = json.loads(handle_search(mem_svc, query="Searchable with None limit", limit=None, project="test"))
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["title"] == "Searchable with None limit"

    def test_handle_context(self, mem_svc):
        handle_save(mem_svc, title="Ctx Test", what="Context item", project="test")
        result = json.loads(handle_context(mem_svc, project="test"))
        assert result["total"] >= 1
        assert len(result["memories"]) >= 1

    def test_handle_context_none_limit_and_detail_fall_back_to_defaults(self, mem_svc):
        handle_save(mem_svc, title="Ctx None Test", what="Context item", why="Because", project="test")
        result = json.loads(handle_context(mem_svc, project="test", limit=None, detail=None))
        assert result["total"] >= 1
        assert len(result["memories"]) >= 1
        mem = result["memories"][0]
        assert "what" in mem
        assert "why" not in mem

    def test_handle_details(self, mem_svc):
        saved = json.loads(
            handle_save(
                mem_svc,
                title="Detail Test",
                what="Has details",
                details="Full body content",
                project="test",
            )
        )
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

    def test_journey_show_includes_event_history(self, container, journey_svc):
        journey = json.loads(handle_journey_start(journey_svc, title="J", project="test"))
        handle_journey_update(journey_svc, journey_id=journey["id"], summary="Investigating")
        handle_journey_complete(journey_svc, journey_id=journey["id"], summary="Resolved")

        result = json.loads(handle_journey_show(container, journey_id=journey["id"]))
        assert [event["event_type"] for event in result["events"]] == ["updated", "completed"]


class TestArtifactToolHandlers:
    def test_search_and_details(self, container):
        from arcane.domain.models import Artifact

        artifact = Artifact(
            artifact_type="commit",
            external_id="abc123",
            title="Fix retry behavior",
            project="test",
            raw_data={"body": "Use exponential backoff"},
        )
        container.artifact_repo.insert(artifact.model_dump())

        results = json.loads(handle_artifact_search(container, query="exponential", project="test"))
        details = json.loads(handle_artifact_details(container, artifact_id=artifact.id))

        assert results[0]["id"] == artifact.id
        assert details["raw_data"] == {"body": "Use exponential backoff"}

    def test_handle_journey_list(self, journey_svc):
        handle_journey_start(journey_svc, title="J1", project="test")
        handle_journey_start(journey_svc, title="J2", project="test")
        result = json.loads(handle_journey_list(journey_svc, project="test"))
        assert len(result) == 2


class TestRelationshipToolHandlers:
    @staticmethod
    def _create_entities(container):
        """Create a real memory and journey in the DB, return their IDs."""
        from arcane.domain.models import Journey
        from tests.conftest import make_memory_dict

        mem = make_memory_dict()
        container.memory_repo.insert(mem)
        j = Journey(title="Test Journey", project="test-project")
        container.journey_repo.insert(j.model_dump())
        return mem["id"], j.id

    def test_handle_link(self, container):
        mem_id, j_id = self._create_entities(container)
        result = json.loads(
            handle_link(
                container,
                source_type="memory",
                source_id=mem_id,
                target_type="journey",
                target_id=j_id,
                relation="part_of",
            )
        )
        assert result["created"] is True
        assert result["id"]

    def test_handle_link_nonexistent_source(self, container):
        _, j_id = self._create_entities(container)
        result = json.loads(
            handle_link(
                container,
                source_type="memory",
                source_id="nonexistent-id",
                target_type="journey",
                target_id=j_id,
                relation="part_of",
            )
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_handle_link_nonexistent_target(self, container):
        mem_id, _ = self._create_entities(container)
        result = json.loads(
            handle_link(
                container,
                source_type="memory",
                source_id=mem_id,
                target_type="journey",
                target_id="nonexistent-id",
                relation="part_of",
            )
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_handle_link_invalid_type(self, container):
        result = json.loads(
            handle_link(
                container,
                source_type="invalid",
                source_id="m1",
                target_type="journey",
                target_id="j1",
                relation="part_of",
            )
        )
        assert "error" in result

    def test_handle_link_invalid_relation(self, container):
        result = json.loads(
            handle_link(
                container,
                source_type="memory",
                source_id="m1",
                target_type="journey",
                target_id="j1",
                relation="bad_relation",
            )
        )
        assert "error" in result

    def test_handle_trace(self, container):
        mem_id, j_id = self._create_entities(container)
        handle_link(
            container,
            source_type="memory",
            source_id=mem_id,
            target_type="journey",
            target_id=j_id,
            relation="part_of",
        )
        result = json.loads(handle_trace(container, entity_type="memory", entity_id=mem_id))
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


class TestMcpServerCallTool:
    @staticmethod
    def _call_tool(container, name: str, arguments: dict | None = None):
        server = _create_server(container)
        handler = server.request_handlers[CallToolRequest]
        request = CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
        return asyncio.run(handler(request)).root

    def test_server_reports_arcane_version(self, container):
        assert _create_server(container).version == __version__

    def test_memory_save_stamps_source_from_client_info(self, container, monkeypatch):
        from mcp.server.lowlevel.server import Server

        class _FakeClientInfo:
            name = "Claude Code"

        class _FakeClientParams:
            clientInfo = _FakeClientInfo()

        class _FakeSession:
            client_params = _FakeClientParams()

        class _FakeRequestContext:
            session = _FakeSession()

        monkeypatch.setattr(Server, "request_context", property(lambda self: _FakeRequestContext()))

        result = self._call_tool(container, "memory_save", {"title": "Stamped", "what": "via clientInfo"})
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        mem = container.memory_repo.get(payload["id"])
        assert mem["source"] == "claude-code"

    def test_memory_save_explicit_source_wins_over_client_info(self, container, monkeypatch):
        from mcp.server.lowlevel.server import Server

        class _FakeClientInfo:
            name = "Claude Code"

        class _FakeClientParams:
            clientInfo = _FakeClientInfo()

        class _FakeSession:
            client_params = _FakeClientParams()

        class _FakeRequestContext:
            session = _FakeSession()

        monkeypatch.setattr(Server, "request_context", property(lambda self: _FakeRequestContext()))

        result = self._call_tool(
            container, "memory_save", {"title": "Explicit", "what": "explicit source wins", "source": "codex"}
        )
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        mem = container.memory_repo.get(payload["id"])
        assert mem["source"] == "codex"

    def test_memory_context_succeeds_via_call_tool(self, container):
        mem_svc = MemoryService(container)
        handle_save(mem_svc, title="Context via MCP", what="Context item", project="test")
        result = self._call_tool(container, "memory_context", {"project": "test", "limit": 5, "detail": "standard"})
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["total"] >= 1
        assert payload["memories"][0]["title"] == "Context via MCP"

    def test_memory_search_succeeds_via_call_tool(self, container):
        mem_svc = MemoryService(container)
        handle_save(mem_svc, title="Search via MCP", what="Search content", project="test")
        result = self._call_tool(container, "memory_search", {"project": "test", "query": "Search via MCP", "limit": 5})
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload[0]["title"] == "Search via MCP"

    def test_artifact_search_succeeds_via_call_tool(self, container):
        from arcane.domain.models import Artifact

        artifact = Artifact(
            artifact_type="commit",
            external_id="abc123",
            title="Fix retry behavior",
            project="test",
            raw_data={"body": "Use exponential backoff"},
        )
        container.artifact_repo.insert(artifact.model_dump())

        result = self._call_tool(container, "artifact_search", {"query": "exponential", "project": "test"})

        assert result.isError is False
        assert json.loads(result.content[0].text)[0]["id"] == artifact.id

    def test_journey_start_succeeds_via_call_tool(self, container):
        result = self._call_tool(
            container,
            "journey_start",
            {"title": "Journey via MCP", "project": "test", "linear_issue_id": ""},
        )
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["title"] == "Journey via MCP"
        assert payload["project"] == "test"


class TestMemoryContextDetailLevels:
    def test_context_default_is_standard(self, mem_svc):
        handle_save(mem_svc, title="Context Test", what="the what", why="the why", impact="the impact", project="test")
        result = json.loads(handle_context(mem_svc, project="test"))
        mem = result["memories"][0]
        # standard: has title, category, tags, date, what — no why, no impact
        assert "title" in mem
        assert "tags" in mem
        assert "date" in mem
        assert "why" not in mem
        assert "impact" not in mem

    def test_context_minimal(self, mem_svc):
        handle_save(mem_svc, title="Min Test", what="the what", why="the why", project="test")
        result = json.loads(handle_context(mem_svc, project="test", detail="minimal"))
        mem = result["memories"][0]
        assert "title" in mem
        assert "category" in mem
        assert "what" not in mem
        assert "tags" not in mem
        assert "why" not in mem

    def test_context_full(self, mem_svc):
        handle_save(mem_svc, title="Full Test", what="the what", why="the why", impact="the impact", project="test")
        result = json.loads(handle_context(mem_svc, project="test", detail="full"))
        mem = result["memories"][0]
        assert "title" in mem
        assert "what" in mem
        assert "why" in mem
        assert "impact" in mem

    def test_context_invalid_detail_falls_back_to_standard(self, mem_svc):
        handle_save(mem_svc, title="Fallback Test", what="the what", project="test")
        result = json.loads(handle_context(mem_svc, project="test", detail="bogus"))
        mem = result["memories"][0]
        # standard has tags but not why
        assert "tags" in mem
        assert "why" not in mem


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

    def test_handle_draft_blog_project_mode(self, container):
        """draft_blog with project but no journey_id should return a brief from memories."""
        from tests.conftest import make_memory_dict

        mem = make_memory_dict(title="Blog mem", what="We did a thing", project="blogproj")
        container.memory_repo.insert(mem)
        result = json.loads(handle_draft_blog(container, project="blogproj"))
        assert "brief" in result
        assert "blogproj" in result["brief"]
        assert "error" not in result


class TestIsError:
    """Logical errors must set isError=True so MCP clients can distinguish them."""

    @staticmethod
    def _call_tool(container, name: str, arguments: dict | None = None):
        server = _create_server(container)
        handler = server.request_handlers[CallToolRequest]
        request = CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
        return asyncio.run(handler(request)).root

    def test_memory_details_not_found_is_error(self, container):
        result = self._call_tool(container, "memory_details", {"memory_id": "nonexistent"})
        assert result.isError is True

    def test_memory_delete_not_found_is_error(self, container):
        result = self._call_tool(container, "memory_delete", {"memory_id": "nonexistent"})
        assert result.isError is True
        text = result.content[0].text
        assert "not enabled" not in text
        assert "Memory not found: nonexistent" in text

    def test_journey_update_not_found_is_error(self, container):
        result = self._call_tool(container, "journey_update", {"journey_id": "nope"})
        assert result.isError is True

    def test_journey_complete_not_found_is_error(self, container):
        result = self._call_tool(container, "journey_complete", {"journey_id": "nope"})
        assert result.isError is True

    def test_insights_ack_not_found_is_error(self, container):
        result = self._call_tool(container, "insights_ack", {"insight_id": "nope"})
        assert result.isError is True
        text = result.content[0].text
        assert "not enabled" not in text
        assert "ID prefix must be at least" in text

    def test_draft_adr_not_found_is_error(self, container):
        result = self._call_tool(container, "draft_adr", {"memory_id": "nope"})
        assert result.isError is True
        text = result.content[0].text
        assert "not enabled" not in text
        assert "Memory nope not found" in text

    def test_link_nonexistent_source_is_error(self, container):
        result = self._call_tool(
            container,
            "link",
            {
                "source_type": "memory",
                "source_id": "nope",
                "target_type": "journey",
                "target_id": "nope",
                "relation": "part_of",
            },
        )
        assert result.isError is True
        text = result.content[0].text
        assert "not enabled" not in text
        assert "Source memory not found: nope" in text

    def test_success_is_not_error(self, container):
        """Successful ops must still have isError=False."""
        svc = MemoryService(container)
        handle_save(svc, title="IsError OK", what="fine", project="test")
        result = self._call_tool(container, "memory_search", {"query": "IsError OK", "project": "test"})
        assert result.isError is False


class TestMemoryContextQuery:
    """memory_context should accept a query param and do semantic-relevant retrieval."""

    def test_context_with_query_via_call_tool(self, container):
        server = _create_server(container)
        handler = server.request_handlers[CallToolRequest]
        svc = MemoryService(container)
        handle_save(svc, title="SQLite chosen", what="We picked SQLite for simplicity", project="qp")
        handle_save(svc, title="Redis cache", what="We use Redis for rate limiting", project="qp")

        req = CallToolRequest(
            params=CallToolRequestParams(
                name="memory_context",
                arguments={"project": "qp", "query": "database", "limit": 5},
            )
        )
        result = asyncio.run(handler(req)).root
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert "memories" in payload

    def test_context_query_param_accepted(self, container):
        """handle_context should not raise when query passed."""
        svc = MemoryService(container)
        handle_save(svc, title="Query test", what="hello world", project="qtest")
        result = json.loads(handle_context(svc, project="qtest", query="hello"))
        assert "memories" in result


class TestJourneyShow:
    def test_journey_show_found(self, container):
        svc = JourneyService(container)
        j = json.loads(handle_journey_start(svc, title="Showable", project="test"))
        result = json.loads(handle_journey_show(container, journey_id=j["id"]))
        assert result["id"] == j["id"]
        assert result["title"] == "Showable"
        assert "linked_memories" in result

    def test_journey_show_not_found(self, container):
        result = json.loads(handle_journey_show(container, journey_id="nope"))
        assert "error" in result

    def test_journey_show_via_call_tool(self, container):
        server = _create_server(container)
        handler = server.request_handlers[CallToolRequest]
        svc = JourneyService(container)
        j = json.loads(handle_journey_start(svc, title="Show via MCP", project="test"))

        req = CallToolRequest(params=CallToolRequestParams(name="journey_show", arguments={"journey_id": j["id"]}))
        result = asyncio.run(handler(req)).root
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["title"] == "Show via MCP"

    def test_journey_show_not_found_is_error(self, container):
        server = _create_server(container)
        handler = server.request_handlers[CallToolRequest]
        req = CallToolRequest(params=CallToolRequestParams(name="journey_show", arguments={"journey_id": "nope"}))
        result = asyncio.run(handler(req)).root
        assert result.isError is True


class TestCategoryCoercionWarning:
    def test_invalid_category_includes_warning(self, mem_svc):
        result = json.loads(
            handle_save(
                mem_svc,
                title="Bad Cat",
                what="Invalid category",
                category="invalid_cat",
                project="test",
            )
        )
        assert result["action"] == "created"
        # Must warn the caller that category was coerced
        assert any("invalid_cat" in w for w in result["warnings"])

    def test_valid_category_no_coercion_warning(self, mem_svc):
        result = json.loads(handle_save(mem_svc, title="Good Cat", what="Valid", category="decision", project="test"))
        coercion_warnings = [w for w in result["warnings"] if "coerced" in w.lower() or "invalid" in w.lower()]
        assert coercion_warnings == []


class TestSearchTTLConfidence:
    def test_search_result_includes_ttl_and_confidence(self, mem_svc):
        handle_save(mem_svc, title="TTL mem", what="expires soon", ttl_days=30, confidence=0.9, project="test")
        results = json.loads(handle_search(mem_svc, query="TTL mem", project="test"))
        assert len(results) >= 1
        r = results[0]
        assert "ttl_days" in r
        assert "confidence" in r
        assert r["ttl_days"] == 30
        assert r["confidence"] == pytest.approx(0.9, abs=0.01)

    def test_search_result_ttl_none_when_not_set(self, mem_svc):
        handle_save(mem_svc, title="No TTL mem", what="permanent", project="test")
        results = json.loads(handle_search(mem_svc, query="No TTL mem", project="test"))
        assert len(results) >= 1
        assert results[0]["ttl_days"] is None
        assert results[0]["confidence"] is None


class TestInsightsProjectCanonicalization:
    def test_handle_insights_canonicalizes_explicit_project(self, container):
        from arcane.domain.models import Insight

        insight = Insight(
            insight_type="ci_flake",
            title="Flake in canonical project",
            body="details",
            project="edition-x",
        )
        container.insight_repo.insert(insight.model_dump())

        result = json.loads(handle_insights(container, project="Edition X"))
        assert len(result) == 1
        assert result[0]["title"] == "Flake in canonical project"


class TestMemoryUpdateHandler:
    def test_update_memory(self, container):
        from arcane.mcp_server.tools.memory_tools import handle_update

        svc = MemoryService(container)
        r = json.loads(handle_save(svc, title="To update", what="Old", project="p"))

        result = json.loads(handle_update(svc, memory_id=r["id"], what="New", tags=["t1"]))

        assert result["updated"] is True
        mem = container.memory_repo.get(r["id"])
        assert mem["what"] == "New"
        assert mem["tags"] == ["t1"]

    def test_update_missing_is_error(self, container):
        from arcane.mcp_server.tools.memory_tools import handle_update

        svc = MemoryService(container)
        result = json.loads(handle_update(svc, memory_id="no-such-id", what="x"))
        assert "error" in result


class TestJourneyLifecycleHandlers:
    def test_abandon(self, container):
        from arcane.mcp_server.tools.journey_tools import handle_journey_abandon

        js = JourneyService(container)
        j = js.start("Stuck test journey", project="p")

        result = json.loads(handle_journey_abandon(js, journey_id=j["id"], reason="test junk"))

        assert result["abandoned"] is True
        assert js.get(j["id"])["status"] == "abandoned"

    def test_abandon_missing_is_error(self, container):
        from arcane.mcp_server.tools.journey_tools import handle_journey_abandon

        result = json.loads(handle_journey_abandon(JourneyService(container), journey_id="nope"))
        assert "error" in result

    def test_delete(self, container):
        from arcane.mcp_server.tools.journey_tools import handle_journey_delete

        js = JourneyService(container)
        j = js.start("Delete via MCP", project="p")

        result = json.loads(handle_journey_delete(js, journey_id=j["id"]))

        assert result["deleted"] is True
        assert js.get(j["id"]) is None

    def test_journey_list_annotates_stale(self, container):
        from datetime import datetime, timedelta, timezone

        from arcane.mcp_server.tools.journey_tools import handle_journey_list

        js = JourneyService(container)
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        container.journey_repo.insert(
            {
                "id": "j-stale-mcp",
                "title": "Old spike",
                "project": "p",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": old,
            }
        )
        js.start("Fresh journey", project="p")

        result = json.loads(handle_journey_list(js, project="p"))

        by_id = {j["id"]: j for j in result}
        assert by_id["j-stale-mcp"]["stale"] is True
        fresh = [j for j in result if j["id"] != "j-stale-mcp"]
        assert all(not j.get("stale") for j in fresh)


class TestContextSurfacesInsights:
    def _insight(self, container, title="Needs attention"):
        from arcane.domain.models import Insight

        insight = Insight(insight_type="health", title=title, body="b", severity="warning", project="p")
        container.insight_repo.insert(insight.model_dump())
        return insight

    def test_standard_detail_includes_unacked_insights(self, container):
        self._insight(container)
        svc = MemoryService(container)
        handle_save(svc, title="A memory", what="Body", project="p")

        result = json.loads(handle_context(svc, project="p", detail="standard"))

        assert "insights" in result
        assert result["insights"][0]["title"] == "Needs attention"

    def test_minimal_detail_omits_insights(self, container):
        self._insight(container)
        svc = MemoryService(container)

        result = json.loads(handle_context(svc, project="p", detail="minimal"))
        assert "insights" not in result

    def test_no_insights_key_when_none_pending(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_context(svc, project="p", detail="standard"))
        assert "insights" not in result

    def test_acknowledged_insights_not_surfaced(self, container):
        insight = self._insight(container)
        container.insight_repo.acknowledge(insight.id)
        svc = MemoryService(container)

        result = json.loads(handle_context(svc, project="p", detail="standard"))
        assert "insights" not in result


class TestContextSurfacesStaleJourneys:
    def test_standard_detail_includes_stale_journey(self, container):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        container.journey_repo.insert(
            {
                "id": "j-stale-context",
                "title": "Old spike",
                "project": "p",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": old,
            }
        )
        svc = MemoryService(container)

        result = json.loads(handle_context(svc, project="p", detail="standard"))

        assert "stale_journeys" in result
        assert len(result["stale_journeys"]) == 1
        assert result["stale_journeys"][0]["id"] == "j-stale-context"
        assert result["stale_journeys"][0]["title"] == "Old spike"
        assert "idle >14 days" in result["message"]

    def test_no_stale_journeys_key_when_fresh(self, container):
        js = JourneyService(container)
        js.start("Fresh journey", project="p")
        svc = MemoryService(container)

        result = json.loads(handle_context(svc, project="p", detail="standard"))

        assert "stale_journeys" not in result

    def test_minimal_detail_omits_stale_journeys(self, container):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        container.journey_repo.insert(
            {
                "id": "j-stale-minimal",
                "title": "Old spike",
                "project": "p",
                "status": "active",
                "started_at": old,
                "created_at": old,
                "updated_at": old,
            }
        )
        svc = MemoryService(container)

        result = json.loads(handle_context(svc, project="p", detail="minimal"))

        assert "stale_journeys" not in result


class TestEmptyProjectGuard:
    def test_save_with_blank_project_warns(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_save(svc, title="Orphan", what="Body", project="   "))

        assert any("empty_project" in w for w in result.get("warnings", []))

    def test_org_scope_save_does_not_warn(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_save(svc, title="Org fact", what="Body", scope="org", org="acme"))

        assert not any("empty_project" in w for w in result.get("warnings", []))

    def test_normal_save_does_not_warn(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_save(svc, title="Normal", what="Body", project="p"))

        assert not any("empty_project" in w for w in result.get("warnings", []))


class TestAnalyzeHealth:
    def test_analyze_health_creates_insights(self, container):
        from arcane.mcp_server.tools.ingestion_tools import handle_analyze
        from tests.conftest import make_memory_dict

        container.memory_repo.insert(make_memory_dict(project="p"))

        result = json.loads(handle_analyze(container, plugin_name="health", project="p"))

        assert result["plugin"] == "health"
        assert result["insights_created"] >= 1
        stored = container.insight_repo.list_all(project="p")
        assert any(i["insight_type"] == "health" for i in stored)
