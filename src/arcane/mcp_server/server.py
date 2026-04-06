"""MCP server exposing all Arcane tools for coding agents."""

from __future__ import annotations

import json
import logging

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from arcane.domain.enums import RelationType
from arcane.mcp_server.tools.content_tools import handle_draft_adr, handle_draft_blog
from arcane.mcp_server.tools.ingestion_tools import (
    handle_analyze,
    handle_ingest_gha,
    handle_ingest_git,
    handle_ingest_linear,
)
from arcane.mcp_server.tools.intelligence_tools import handle_insights, handle_insights_ack
from arcane.mcp_server.tools.journey_tools import (
    handle_journey_complete,
    handle_journey_list,
    handle_journey_start,
    handle_journey_update,
)
from arcane.mcp_server.tools.memory_tools import (
    CONTEXT_DESCRIPTION,
    SAVE_DESCRIPTION,
    SEARCH_DESCRIPTION,
    VALID_CATEGORIES,
    handle_context,
    handle_delete,
    handle_details,
    handle_save,
    handle_search,
)
from arcane.mcp_server.tools.relationship_tools import handle_link, handle_trace
from arcane.services.container import ServiceContainer, create_container
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService

logger = logging.getLogger(__name__)


def _create_server(container: ServiceContainer) -> Server:
    """Create and configure the MCP server with all tools."""
    server = Server("arcane")
    mem_svc = MemoryService(container)
    journey_svc = JourneyService(container)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # ── Memory tools (backward-compatible) ──
            Tool(
                name="memory_save",
                description=SAVE_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title, max 60 chars."},
                        "what": {"type": "string", "description": "1-2 sentences. The essence."},
                        "why": {"type": "string", "description": "Reasoning behind it."},
                        "impact": {"type": "string", "description": "What changed."},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "category": {"type": "string", "enum": list(VALID_CATEGORIES)},
                        "related_files": {"type": "array", "items": {"type": "string"}},
                        "details": {"type": "string", "description": "Full context."},
                        "project": {"type": "string"},
                        "journey_id": {"type": "string", "description": "Link to a journey."},
                    },
                    "required": ["title", "what"],
                },
            ),
            Tool(
                name="memory_search",
                description=SEARCH_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 5},
                        "project": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memory_context",
                description=CONTEXT_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            ),
            Tool(
                name="memory_details",
                description="Get full details for a memory by ID or prefix.",
                inputSchema={
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            ),
            Tool(
                name="memory_delete",
                description="Delete a memory by ID or prefix.",
                inputSchema={
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            ),
            # ── Journey tools ──
            Tool(
                name="journey_start",
                description="Start tracking a decision journey.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "project": {"type": "string"},
                        "linear_issue_id": {"type": "string"},
                    },
                    "required": ["title"],
                },
            ),
            Tool(
                name="journey_update",
                description="Update an active journey with new context.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "journey_id": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["journey_id"],
                },
            ),
            Tool(
                name="journey_complete",
                description="Mark a journey as completed with a summary.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "journey_id": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["journey_id"],
                },
            ),
            Tool(
                name="journey_list",
                description="List decision journeys.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "completed", "abandoned"]},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            ),
            # ── Relationship tools ──
            Tool(
                name="link",
                description="Create a relationship between two entities.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_type": {"type": "string", "enum": ["memory", "journey", "artifact"]},
                        "source_id": {"type": "string"},
                        "target_type": {"type": "string", "enum": ["memory", "journey", "artifact"]},
                        "target_id": {"type": "string"},
                        "relation": {"type": "string", "enum": [r.value for r in RelationType]},
                    },
                    "required": ["source_type", "source_id", "target_type", "target_id", "relation"],
                },
            ),
            Tool(
                name="trace",
                description="Walk the relationship graph from an entity.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity_type": {"type": "string", "enum": ["memory", "journey", "artifact"]},
                        "entity_id": {"type": "string"},
                        "max_depth": {"type": "integer", "default": 5},
                    },
                    "required": ["entity_type", "entity_id"],
                },
            ),
            # ── Intelligence tools ──
            Tool(
                name="insights",
                description="Get recent unacknowledged insights for a project.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            ),
            Tool(
                name="insights_ack",
                description="Acknowledge an insight.",
                inputSchema={
                    "type": "object",
                    "properties": {"insight_id": {"type": "string"}},
                    "required": ["insight_id"],
                },
            ),
            # ── Ingestion tools ──
            Tool(
                name="ingest_git",
                description="Ingest commits from a git repository as artifacts.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "repo_path": {"type": "string", "description": "Path to git repo."},
                        "max_count": {"type": "integer", "default": 100},
                        "journey_id": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="ingest_gha",
                description="Ingest CI runs from GitHub Actions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "project": {"type": "string"},
                        "journey_id": {"type": "string"},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            Tool(
                name="ingest_linear",
                description="Ingest tickets from Linear.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_id": {"type": "string"},
                        "project": {"type": "string"},
                        "journey_id": {"type": "string"},
                    },
                    "required": ["team_id"],
                },
            ),
            # ── Analysis tools ──
            Tool(
                name="analyze",
                description="Run an intelligence analysis plugin (ci_flakes, velocity).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "plugin_name": {"type": "string", "enum": ["ci_flakes", "velocity"]},
                        "project": {"type": "string"},
                    },
                    "required": ["plugin_name"],
                },
            ),
            # ── Content tools ──
            Tool(
                name="draft_blog",
                description="Generate a structured blog brief from a journey.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "journey_id": {"type": "string"},
                        "project": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="draft_adr",
                description="Generate a structured ADR from a decision memory.",
                inputSchema={
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        # All handler functions are synchronous (SQLite + subprocess work).
        # Run them in a thread so the asyncio event loop is never blocked.
        handlers = {
            "memory_save": lambda: handle_save(mem_svc, **arguments),
            "memory_search": lambda: handle_search(mem_svc, **arguments),
            "memory_context": lambda: handle_context(mem_svc, **arguments),
            "memory_details": lambda: handle_details(mem_svc, **arguments),
            "memory_delete": lambda: handle_delete(mem_svc, **arguments),
            "journey_start": lambda: handle_journey_start(journey_svc, **arguments),
            "journey_update": lambda: handle_journey_update(journey_svc, **arguments),
            "journey_complete": lambda: handle_journey_complete(journey_svc, **arguments),
            "journey_list": lambda: handle_journey_list(journey_svc, **arguments),
            "ingest_git": lambda: handle_ingest_git(container, **arguments),
            "ingest_gha": lambda: handle_ingest_gha(container, **arguments),
            "ingest_linear": lambda: handle_ingest_linear(container, **arguments),
            "analyze": lambda: handle_analyze(container, **arguments),
            "link": lambda: handle_link(container, **arguments),
            "trace": lambda: handle_trace(container, **arguments),
            "insights": lambda: handle_insights(container, **arguments),
            "insights_ack": lambda: handle_insights_ack(container, **arguments),
            "draft_blog": lambda: handle_draft_blog(container, **arguments),
            "draft_adr": lambda: handle_draft_adr(container, **arguments),
        }

        handler = handlers.get(name)
        if handler:
            try:
                result = await anyio.to_thread.run_sync(handler)
            except Exception:
                logger.error("Tool '%s' failed", name, exc_info=True)
                result = json.dumps({"error": f"Internal error in tool '{name}'. Check server logs."})
        else:
            logger.warning("Unknown MCP tool requested: %s", name)
            result = json.dumps({"error": f"Unknown tool: {name}"})

        return [TextContent(type="text", text=result)]

    return server


async def run_server() -> None:
    """Run the MCP server with stdio transport."""
    container = create_container()
    try:
        server = _create_server(container)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        container.close()
