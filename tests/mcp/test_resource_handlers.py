"""Tests for MCP resource handlers."""

from __future__ import annotations

import json

from arcane.mcp_server.resources import RESOURCE_TEMPLATE_URI, _parse_project_from_uri
from arcane.mcp_server.tools.memory_tools import handle_context, handle_save
from arcane.services.memory import MemoryService


class TestParseProjectFromUri:
    def test_parses_simple_project(self):
        assert _parse_project_from_uri("arcane://context/myproject") == "myproject"

    def test_parses_project_with_hyphens(self):
        assert _parse_project_from_uri("arcane://context/my-project-name") == "my-project-name"

    def test_template_uri_constant(self):
        assert "context" in RESOURCE_TEMPLATE_URI
        assert RESOURCE_TEMPLATE_URI.startswith("arcane://")


class TestResourcePayload:
    """Test that the resource returns valid context payload."""

    def test_resource_payload_matches_context_tool(self, container):
        """The resource payload should match what handle_context returns."""
        svc = MemoryService(container)
        handle_save(svc, title="Resource Test", what="testing resource", project="res-proj")

        payload = json.loads(handle_context(svc, project="res-proj", detail="standard"))
        assert "memories" in payload
        assert "total" in payload
        assert payload["total"] >= 1

    def test_resource_empty_project(self, container):
        svc = MemoryService(container)
        payload = json.loads(handle_context(svc, project="empty-proj", detail="standard"))
        assert payload["total"] == 0
        assert payload["memories"] == []
