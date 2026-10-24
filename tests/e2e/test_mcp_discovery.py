"""E2E: what the server advertises, its prompts and resources, and how it rejects bad calls."""

from __future__ import annotations

import json
import re
from pathlib import Path

from arcane import __version__
from tests.e2e.conftest import Arcane, Client

CORE_TOOLS = {
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
FULL_ONLY_TOOLS = {
    "memory_delete",
    "journey_delete",
    "artifact_details",
    "link",
    "trace",
    "insights_ack",
    "ingest_git",
    "ingest_gha",
    "ingest_linear",
    "analyze",
    "plugins",
    "draft_blog",
    "draft_adr",
}


async def _tool_names(c: Client) -> set[str]:
    return {tool.name for tool in (await c.session.list_tools()).tools}


def test_core_profile_advertises_and_dispatches_only_core_tools(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[set[str], str]:
        return await _tool_names(c), await c.error("trace", entity_type="memory", entity_id="whatever1")

    names, blocked = arcane.run(scenario, profile="core")
    assert names == CORE_TOOLS
    assert "ARCANE_TOOL_PROFILE=full" in blocked

    names, _ = arcane.run(scenario, profile="bogus")
    assert names == CORE_TOOLS


def test_full_profile_advertises_every_tool(arcane: Arcane) -> None:
    async def scenario(c: Client) -> set[str]:
        return await _tool_names(c)

    assert arcane.run(scenario) == CORE_TOOLS | FULL_ONLY_TOOLS


def test_server_identifies_itself(arcane: Arcane) -> None:
    async def handshake(c: Client) -> tuple[str, str]:
        # initialize() already ran; a second one returns the same server info.
        info = (await c.session.initialize()).server_info
        return info.name, info.version

    assert arcane.run(handshake) == ("arcane", __version__)


def test_prompts_render_with_their_arguments(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, object]:
        prompts = {p.name: p for p in (await c.session.list_prompts()).prompts}

        def text(result: object) -> str:
            return result.messages[0].content.text  # type: ignore[attr-defined]

        return {
            "names": set(prompts),
            "recall_required": {a.name for a in prompts["recall"].arguments or [] if a.required},
            "recall": text(await c.session.get_prompt("recall", {"project": "widget", "query": "sqlite"})),
            "catchup": text(await c.session.get_prompt("catchup", {"project": "widget"})),
            "journey": text(await c.session.get_prompt("journey", {"journey_id": "abc12345"})),
            "missing_query": text(await c.session.get_prompt("recall", {"project": "widget"})),
            "unknown": text(await c.session.get_prompt("nope", {})),
        }

    out = arcane.run(scenario)
    assert out["names"] == {"recall", "catchup", "journey"}
    assert out["recall_required"] == {"query"}
    assert "widget" in out["recall"] and "sqlite" in out["recall"]
    assert "widget" in out["catchup"]
    assert "abc12345" in out["journey"]
    assert out["missing_query"] == "Error building prompt 'recall'."
    assert out["unknown"] == "Unknown prompt: nope"


def test_project_context_resource_matches_the_context_tool(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[object, ...]:
        await c.call("memory_save", title="Resource check", what="Seen through the resource", category="context")
        templates = (await c.session.list_resource_templates()).resource_templates
        resources = (await c.session.list_resources()).resources
        read = await c.session.read_resource("arcane://context/widget")  # type: ignore[arg-type]
        tool = await c.call("memory_context", project="widget")
        return templates[0].uri_template, resources, json.loads(read.contents[0].text), tool  # type: ignore[union-attr]

    template, resources, resource, tool = arcane.run(scenario)
    assert template == "arcane://context/{project}"
    assert resources == []
    assert [m["title"] for m in resource["memories"]] == ["Resource check"]
    assert resource["memories"] == tool["memories"]


def test_bad_calls_get_errors_the_agent_can_act_on(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[str, ...]:
        return (
            await c.error("no_such_tool"),
            await c.error("memory_details", memory_id="abcdefgh", verbose=True),
            await c.error("memory_save", title="t", what="w", category="nonsense"),
            await c.error("analyze", plugin_name="nonsense"),
            await c.error("memory_save", title="t", what="w", confidence=1.5),
        )

    unknown, extra_arg, bad_category, bad_plugin, bad_confidence = arcane.run(scenario)
    assert unknown == "Unknown tool: no_such_tool"
    assert "Invalid arguments for tool 'memory_details'" in extra_arg
    assert "'nonsense' is not one of" in bad_category
    assert "'nonsense' is not one of" in bad_plugin
    assert "1.5 is greater than the maximum of 1" in bad_confidence


def test_every_id_argument_rejects_ambiguous_short_prefixes(arcane: Arcane) -> None:
    calls: list[tuple[str, dict[str, object]]] = [
        ("memory_details", {"memory_id": "abc"}),
        ("memory_update", {"memory_id": "abc", "what": "x"}),
        ("memory_delete", {"memory_id": "abc"}),
        ("journey_update", {"journey_id": "abc", "summary": "x"}),
        ("journey_complete", {"journey_id": "abc"}),
        ("journey_abandon", {"journey_id": "abc"}),
        ("journey_show", {"journey_id": "abc"}),
        ("journey_delete", {"journey_id": "abc"}),
        ("artifact_details", {"artifact_id": "abc"}),
        ("trace", {"entity_type": "memory", "entity_id": "abc"}),
        ("insights_ack", {"insight_id": "abc"}),
        ("draft_adr", {"memory_id": "abc"}),
        ("draft_blog", {"journey_id": "abc"}),
        ("ingest_git", {"journey_id": "abc"}),
        (
            "link",
            {
                "source_type": "memory",
                "source_id": "abc",
                "target_type": "memory",
                "target_id": "abcdefgh",
                "relation": "references",
            },
        ),  # fmt: skip
    ]

    async def scenario(c: Client) -> dict[str, str]:
        return {name: await c.error(name, **args) for name, args in calls}

    errors = arcane.run(scenario)
    assert {name for name, e in errors.items() if "at least 8 characters" not in e} == set()


def test_unknown_ids_and_odd_limits(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[str, list[object], dict[str, object]]:
        for n in range(7):
            await c.call("memory_save", title=f"Note {n}", what="limit check")
        return (
            await c.error("trace", entity_type="journey", entity_id="00000000-0000-0000-0000-000000000000"),
            await c.call("memory_search", query="limit check", limit=0),
            await c.call("memory_context", limit=0),
        )

    trace_missing, search, context = arcane.run(scenario)
    assert trace_missing.startswith("Journey not found")
    assert len(search) == 5  # a non-positive limit falls back to the default
    assert context["showing"] == 7


def test_tool_reference_documents_exactly_the_tools_the_server_exposes(arcane: Arcane) -> None:
    """``docs/mcp-tools.md`` is the contract readers see; drift from it is a lie.

    The reference once missed five tools entirely while still claiming a total
    that happened to be right.
    """
    reference = (Path(__file__).resolve().parents[2] / "docs" / "mcp-tools.md").read_text(encoding="utf-8")
    tool_section = reference.split("## MCP Resources", 1)[0]
    documented = {
        name: profile
        for name, profile in re.findall(r"^### `([a-z_]+)`\n\n\*\*Profile:\*\* `(core|full)`", tool_section, re.M)
    }

    async def scenario(client: Client) -> dict[str, str]:
        tools = (await client.session.list_tools()).tools
        return {tool.name: ("core" if tool.name in CORE_TOOLS else "full") for tool in tools}

    exposed = arcane.run(scenario, profile="full")

    assert documented.keys() == exposed.keys(), (
        f"undocumented: {sorted(exposed.keys() - documented.keys())}; "
        f"documented but absent: {sorted(documented.keys() - exposed.keys())}"
    )
    wrong = {name: (documented[name], exposed[name]) for name in exposed if documented[name] != exposed[name]}
    assert not wrong, f"profile documented incorrectly (documented, actual): {wrong}"
    assert f"Arcane exposes {len(exposed)} tools" in reference
