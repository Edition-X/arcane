"""MCP server exposing all Arcane tools for coding agents."""

from __future__ import annotations

import inspect
import json
import logging
import os
from collections.abc import Callable
from typing import Any, cast

import anyio
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourceTemplate,
    TextContent,
    Tool,
)
from pydantic import AnyUrl

from arcane import __version__
from arcane.domain.enums import RelationType
from arcane.domain.scope import slugify
from arcane.mcp_server.prompts import (
    PROMPTS,
    build_catchup_prompt,
    build_journey_prompt,
    build_recall_prompt,
)
from arcane.mcp_server.resources import RESOURCE_TEMPLATE_URI, _parse_project_from_uri
from arcane.mcp_server.tools.artifact_tools import handle_artifact_details, handle_artifact_search
from arcane.mcp_server.tools.content_tools import handle_draft_adr, handle_draft_blog
from arcane.mcp_server.tools.ingestion_tools import (
    handle_analyze,
    handle_ingest_gha,
    handle_ingest_git,
    handle_ingest_linear,
)
from arcane.mcp_server.tools.intelligence_tools import handle_insights, handle_insights_ack
from arcane.mcp_server.tools.journey_tools import (
    handle_journey_abandon,
    handle_journey_complete,
    handle_journey_delete,
    handle_journey_list,
    handle_journey_show,
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
    handle_update,
)
from arcane.mcp_server.tools.relationship_tools import handle_link, handle_trace
from arcane.services.container import ServiceContainer, create_container, start_embedding_backend
from arcane.services.journey import JourneyService
from arcane.services.memory import MemoryService

logger = logging.getLogger(__name__)

# Tools advertised by default. Everything else ("full" profile only) was
# called fewer than ten times across every harness and all time, per usage
# data reviewed for the "Tool profiles: core by default" decision.
CORE_TOOLS = frozenset(
    {
        "memory_save",
        "memory_search",
        "memory_context",
        "memory_details",
        "memory_update",
        "journey_start",
        "journey_update",
        "journey_complete",
        "journey_abandon",
        "journey_list",
        "journey_show",
        "artifact_search",
        "insights",
    }
)


def _tool_profile() -> str:
    """Read the active tool profile from the environment at call time.

    Read on each call (not cached at import) so tests can toggle it with
    monkeypatch.setenv/delenv without recreating the server.
    """
    value = os.environ.get("ARCANE_TOOL_PROFILE", "core").strip().lower()
    return value if value in {"core", "full"} else "core"


def _create_server(container: ServiceContainer) -> Server:
    """Create and configure the MCP server with all tools."""
    server = Server("arcane", version=__version__)
    mem_svc = MemoryService(container)
    journey_svc = JourneyService(container)

    def _client_name() -> str | None:
        """Best-effort slug of the connecting MCP client's name (e.g. "claude-code").

        The initialize handshake's clientInfo.name is only available inside a
        request context, and any attribute along the path may be missing
        (notably in tests), so this is defensive end to end.
        """
        try:
            params = server.request_context.session.client_params
            name = params.clientInfo.name if params and params.clientInfo else None
        except (LookupError, AttributeError):
            return None
        return slugify(name) if name else None

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        all_tools = [
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
                        "org": {
                            "type": "string",
                            "description": "Company/org slug. Omit to auto-detect from the git remote owner.",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["project", "org", "global"],
                            "default": "project",
                            "description": (
                                "Knowledge layer: project = this repo (default); "
                                "org = company-wide, shared across all the org's repos; "
                                "global = applies everywhere."
                            ),
                        },
                        "journey_id": {"type": "string", "description": "Link to a journey."},
                        "ttl_days": {
                            "type": "integer",
                            "description": "Days until this memory expires. Omit for permanent memories.",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence in accuracy 0.0–1.0. Default: omit.",
                        },
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
                        "org": {"type": "string", "description": "Org slug. Omit to auto-detect from the git remote."},
                        "include_org": {"type": "boolean", "default": True},
                        "include_global": {"type": "boolean", "default": True},
                        "detail": {
                            "type": "string",
                            "enum": ["minimal", "standard", "full"],
                            "default": "standard",
                            "description": (
                                "minimal: id, title, category, score. "
                                "standard: adds what, tags, project, date, has_details. "
                                "full: adds why and impact."
                            ),
                        },
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
                        "detail": {
                            "type": "string",
                            "enum": ["minimal", "standard", "full"],
                            "default": "standard",
                            "description": (
                                "Level of detail per memory. "
                                "minimal=title+category (~500 tokens), "
                                "standard=+tags+what (default), "
                                "full=all fields."
                            ),
                        },
                        "query": {
                            "type": "string",
                            "description": (
                                "Optional topic query. When provided, returns semantically relevant "
                                "memories for this topic instead of most-recent."
                            ),
                        },
                        "org": {"type": "string", "description": "Org slug. Omit to auto-detect from the git remote."},
                        "scope": {
                            "type": "string",
                            "enum": ["project", "org", "global"],
                            "description": (
                                "Narrow retrieval to one layer. Omit for the full project + org + global chain."
                            ),
                        },
                        "include_org": {"type": "boolean", "default": True},
                        "include_global": {"type": "boolean", "default": True},
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
                name="memory_update",
                description=(
                    "Update an existing memory in place — what, why, impact, tags, or appended "
                    "details. Prefer this over memory_save when a near_duplicate warning points "
                    "at an existing memory."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID or prefix."},
                        "what": {"type": "string"},
                        "why": {"type": "string"},
                        "impact": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "details_append": {"type": "string", "description": "Text appended to details."},
                    },
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
                name="journey_abandon",
                description="Mark a journey as abandoned (dead end, superseded, or test junk).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "journey_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["journey_id"],
                },
            ),
            Tool(
                name="journey_delete",
                description="Delete a journey and its relationships. Linked memories survive.",
                inputSchema={
                    "type": "object",
                    "properties": {"journey_id": {"type": "string"}},
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
            Tool(
                name="journey_show",
                description=(
                    "Get full details for a journey — title, status, summary, append-only event history, and "
                    "all linked memories and artifacts. Use instead of trace + memory_details loops."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "journey_id": {"type": "string", "description": "Journey ID or prefix."},
                    },
                    "required": ["journey_id"],
                },
            ),
            # ── Artifact tools ──
            Tool(
                name="artifact_search",
                description="Search ingested artifact titles, external IDs, and raw content.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "project": {"type": "string"},
                        "artifact_type": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="artifact_details",
                description="Get full ingested artifact data by ID or prefix.",
                inputSchema={
                    "type": "object",
                    "properties": {"artifact_id": {"type": "string"}},
                    "required": ["artifact_id"],
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
                description="Run an intelligence analysis plugin (velocity, health).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "plugin_name": {"type": "string", "enum": ["velocity", "health"]},
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
        if _tool_profile() == "core":
            return [tool for tool in all_tools if tool.name in CORE_TOOLS]
        return all_tools

    # Tool name → (handler, first positional argument). Every handler is a
    # synchronous function called as handler(target, **arguments).
    handlers: dict[str, tuple[Callable[..., str], Any]] = {
        "memory_save": (handle_save, mem_svc),
        "memory_search": (handle_search, mem_svc),
        "memory_context": (handle_context, mem_svc),
        "memory_details": (handle_details, mem_svc),
        "memory_update": (handle_update, mem_svc),
        "memory_delete": (handle_delete, mem_svc),
        "journey_start": (handle_journey_start, journey_svc),
        "journey_update": (handle_journey_update, journey_svc),
        "journey_complete": (handle_journey_complete, journey_svc),
        "journey_abandon": (handle_journey_abandon, journey_svc),
        "journey_delete": (handle_journey_delete, journey_svc),
        "journey_list": (handle_journey_list, journey_svc),
        "journey_show": (handle_journey_show, container),
        "artifact_search": (handle_artifact_search, container),
        "artifact_details": (handle_artifact_details, container),
        "ingest_git": (handle_ingest_git, container),
        "ingest_gha": (handle_ingest_gha, container),
        "ingest_linear": (handle_ingest_linear, container),
        "analyze": (handle_analyze, container),
        "link": (handle_link, container),
        "trace": (handle_trace, container),
        "insights": (handle_insights, container),
        "insights_ack": (handle_insights_ack, container),
        "draft_blog": (handle_draft_blog, container),
        "draft_adr": (handle_draft_adr, container),
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object] | None) -> CallToolResult:
        args = cast(dict[str, Any], arguments or {})
        if name == "memory_save":
            # Stamp the connecting client as the source unless the caller set one.
            args = {**args, "source": args.get("source") or _client_name()}

        spec = handlers.get(name)
        is_error = False
        if spec and _tool_profile() == "core" and name not in CORE_TOOLS:
            logger.warning("Tool '%s' requested outside the core profile", name)
            result = json.dumps(
                {"error": f"Tool '{name}' is not enabled. Start the server with ARCANE_TOOL_PROFILE=full to use it."}
            )
            is_error = True
        elif spec:
            handler, target = spec
            try:
                # Reject arguments the handler does not take with a message the
                # agent can act on, instead of a TypeError reported as an
                # internal error.
                inspect.signature(handler).bind(target, **args)
            except TypeError as exc:
                result = json.dumps({"error": f"Invalid arguments for tool '{name}': {exc}"})
                is_error = True
            else:
                try:
                    # Handlers are synchronous (SQLite + subprocess work). Run them
                    # in a worker thread so the asyncio event loop is never blocked.
                    result = await anyio.to_thread.run_sync(lambda: handler(target, **args))
                except Exception:
                    logger.error("Tool '%s' failed", name, exc_info=True)
                    result = json.dumps({"error": f"Internal error in tool '{name}'. Check server logs."})
                    is_error = True
        else:
            logger.warning("Unknown MCP tool requested: %s", name)
            result = json.dumps({"error": f"Unknown tool: {name}"})
            is_error = True

        # Detect logical errors returned as {"error": "..."} JSON payloads
        if not is_error:
            try:
                data = json.loads(result)
                if isinstance(data, dict) and "error" in data:
                    is_error = True
            except (json.JSONDecodeError, TypeError):
                pass

        return CallToolResult(content=[TextContent(type="text", text=result)], isError=is_error)

    @server.list_resource_templates()
    async def list_resource_templates() -> list[ResourceTemplate]:
        return [
            ResourceTemplate(
                uriTemplate=RESOURCE_TEMPLATE_URI,
                name="Project memory context",
                description="Recent memories and decisions for a project. Pre-fetched by MCP hosts at session start.",
                mimeType="application/json",
            )
        ]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """Arcane exposes dynamic project context through resource templates."""
        return []

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        project = _parse_project_from_uri(str(uri))
        text = await anyio.to_thread.run_sync(lambda: handle_context(mem_svc, project=project, detail="standard"))
        return [ReadResourceContents(content=text, mime_type="application/json")]

    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name=p["name"],
                description=p["description"],
                arguments=[
                    PromptArgument(
                        name=a["name"],
                        description=a["description"],
                        required=a.get("required", False),
                    )
                    for a in p.get("arguments", [])
                ],
            )
            for p in PROMPTS
        ]

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        args = arguments or {}
        builders = {
            "recall": build_recall_prompt,
            "catchup": build_catchup_prompt,
            "journey": build_journey_prompt,
        }
        builder = builders.get(name)
        if builder is None:
            return GetPromptResult(
                description=f"Unknown prompt: {name}",
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(type="text", text=f"Unknown prompt: {name}"),
                    )
                ],
            )
        try:
            raw = await anyio.to_thread.run_sync(lambda: builder(args))
        except Exception:
            logger.error("Prompt '%s' builder failed", name, exc_info=True)
            return GetPromptResult(
                description=f"Error building prompt: {name}",
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(type="text", text=f"Error building prompt '{name}'."),
                    )
                ],
            )
        messages = [
            PromptMessage(
                role=m["role"],
                content=TextContent(type="text", text=m["content"]["text"]),
            )
            for m in raw["messages"]
        ]
        return GetPromptResult(description=raw.get("description", ""), messages=messages)

    return server


async def run_server() -> None:
    """Run the MCP server with stdio transport."""
    container = create_container()
    start_embedding_backend(container.config)
    try:
        server = _create_server(container)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        container.close()
