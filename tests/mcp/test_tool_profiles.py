"""Tests for the ARCANE_TOOL_PROFILE core/full tool gating."""

import asyncio

from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from arcane.mcp_server.server import CORE_TOOLS, _create_server


def _list_tools(container):
    server = _create_server(container)
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest())).root
    return result.tools


def _call_tool(container, name: str, arguments: dict | None = None):
    server = _create_server(container)
    handler = server.request_handlers[CallToolRequest]
    request = CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
    return asyncio.run(handler(request)).root


class TestToolProfileDefault:
    def test_default_profile_lists_only_core_tools(self, container, monkeypatch):
        monkeypatch.delenv("ARCANE_TOOL_PROFILE", raising=False)
        tools = _list_tools(container)
        assert len(tools) == len(CORE_TOOLS)
        assert {tool.name for tool in tools} == set(CORE_TOOLS)


class TestToolProfileFull:
    def test_full_profile_lists_more_than_core_and_every_tool_dispatches(self, container, monkeypatch):
        monkeypatch.setenv("ARCANE_TOOL_PROFILE", "full")
        tools = _list_tools(container)
        names = {tool.name for tool in tools}

        # The full profile must be a strict superset of core, and its size is
        # whatever server.py's dispatch table currently registers -- not a
        # literal we'd have to update by hand every time a tool is added.
        assert CORE_TOOLS <= names
        assert len(names) > len(CORE_TOOLS)

        # Every advertised tool must actually be wired into call_tool's
        # dispatch table (not merely listed), so drive each one and confirm
        # none come back as "Unknown tool" -- the sentinel used only for
        # names call_tool has never heard of.
        for name in names:
            result = _call_tool(container, name, {})
            text = result.content[0].text
            assert f"Unknown tool: {name}" not in text
            assert "not enabled" not in text


class TestToolProfileBogus:
    def test_bogus_profile_behaves_as_core(self, container, monkeypatch):
        monkeypatch.setenv("ARCANE_TOOL_PROFILE", "bogus")
        tools = _list_tools(container)
        assert len(tools) == len(CORE_TOOLS)
        assert {tool.name for tool in tools} == set(CORE_TOOLS)


class TestCallToolProfileGating:
    def test_trace_blocked_under_core(self, container, monkeypatch):
        monkeypatch.delenv("ARCANE_TOOL_PROFILE", raising=False)
        result = _call_tool(container, "trace", {"entity_type": "memory", "entity_id": "abc"})
        assert result.isError is True
        assert "not enabled" in result.content[0].text
        assert "ARCANE_TOOL_PROFILE=full" in result.content[0].text

    def test_trace_dispatches_under_full(self, container, monkeypatch):
        monkeypatch.setenv("ARCANE_TOOL_PROFILE", "full")
        result = _call_tool(container, "trace", {"entity_type": "memory", "entity_id": "abc"})
        # Not gated: it reaches the real handler, which may itself report a
        # logical error for an unknown entity, but never the gating text.
        assert "not enabled" not in result.content[0].text
