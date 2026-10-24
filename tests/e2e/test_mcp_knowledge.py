"""E2E: artifacts, the relationship graph, insights and drafted content through the MCP server."""

from __future__ import annotations

from typing import Any

from tests.e2e.conftest import Arcane, Client


def test_git_ingest_makes_commits_searchable(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        first = await c.call("ingest_git", max_count=10)
        again = await c.call("ingest_git", max_count=10)
        hits = await c.call("artifact_search", query="change one")
        return {
            "first": first,
            "again": again,
            "hits": hits,
            "typed": await c.call("artifact_search", query="change", artifact_type="commit"),
            "other_type": await c.call("artifact_search", query="change", artifact_type="ci_run"),
            "details": await c.call("artifact_details", artifact_id=hits[0]["id"][:8]),
            "short": await c.error("artifact_details", artifact_id=hits[0]["id"][:4]),
        }

    out = arcane.run(scenario)
    assert out["first"]["ingested"] == 2
    assert out["again"]["ingested"] == 0
    assert out["again"]["skipped"] == 2
    assert out["hits"][0]["title"] == "feat: change one"
    assert out["hits"][0]["project"] == "widget"
    assert len(out["typed"]) == 2
    assert out["other_type"] == []
    assert out["details"]["external_id"] == out["hits"][0]["external_id"]
    assert "at least 8 characters" in out["short"]


def test_links_store_full_ids_and_trace_walks_them(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        cause = await c.call("memory_save", title="Flaky runner", what="Runner drops", category="bug")
        fix = await c.call("memory_save", title="Pin runner image", what="Pinned", category="decision")
        journey = await c.call("journey_start", title="Runner flakes")
        await c.call(
            "link", source_type="memory", source_id=cause["id"][:8], target_type="memory",
            target_id=fix["id"][:8], relation="resulted_in",
        )  # fmt: skip
        await c.call(
            "link", source_type="memory", source_id=fix["id"][:8], target_type="journey",
            target_id=journey["id"][:8], relation="part_of",
        )  # fmt: skip
        return {
            "ids": (cause["id"], fix["id"], journey["id"]),
            "trace": await c.call("trace", entity_type="memory", entity_id=cause["id"][:8]),
            "missing": await c.error(
                "link",
                source_type="memory",
                source_id="00000000-0000-0000-0000-000000000000",
                target_type="memory",
                target_id=fix["id"],
                relation="references",
            ),  # fmt: skip
            "bad_relation": await c.error(
                "link",
                source_type="memory",
                source_id=cause["id"],
                target_type="memory",
                target_id=fix["id"],
                relation="caused_by_aliens",
            ),  # fmt: skip
        }

    out = arcane.run(scenario)
    cause, fix, journey = out["ids"]
    stored = set(arcane.sql("SELECT source_id, target_id, relation FROM relationships"))
    assert stored == {(cause, fix, "resulted_in"), (fix, journey, "part_of")}
    walked = {(e["source_id"], e["target_id"]) for e in out["trace"]}
    assert walked == {(cause, fix), (fix, journey)}
    assert "not found" in out["missing"].lower()
    assert "is not one of" in out["bad_relation"]


def test_health_insights_surface_in_context_until_acknowledged(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await c.call("memory_save", title="Org note", what="Valid org-scoped knowledge", project="")
        await c.call("memory_save", title="Widget note", what="has a project")
        await c.call("ingest_git", max_count=10)
        out: dict[str, Any] = {
            "health": await c.call("analyze", plugin_name="health"),
            "velocity": await c.call("analyze", plugin_name="velocity"),
        }
        out["insights"] = await c.call("insights")
        out["context"] = await c.call("memory_context")
        out["minimal"] = await c.call("memory_context", detail="minimal")
        for insight in out["insights"]:
            await c.call("insights_ack", insight_id=insight["id"])
        out["after_ack"] = await c.call("insights")
        out["context_after"] = await c.call("memory_context")
        out["ack_missing"] = await c.error("insights_ack", insight_id="00000000-0000-0000-0000-000000000000")
        return out

    out = arcane.run(scenario)
    assert out["health"]["insights_created"] >= 1
    assert out["velocity"]["insights_created"] == 1
    types = {i["type"] for i in out["insights"]}
    assert {"health", "velocity"} <= types
    assert "health_empty_project" not in types
    assert next(i for i in out["insights"] if i["type"] == "velocity")["title"].startswith("Velocity: 2 commits")
    assert {i["id"] for i in out["context"]["insights"]} <= {i["id"] for i in out["insights"]}
    assert out["context"]["insights"]
    assert "insights" not in out["minimal"]
    assert out["after_ack"] == []
    assert "insights" not in out["context_after"]
    assert "not found" in out["ack_missing"].lower()


def test_drafts_build_from_decisions_and_journeys(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        journey = await c.call("journey_start", title="Pick a store")
        await c.call("journey_update", journey_id=journey["id"], summary="Compared options")
        decision = await c.call(
            "memory_save", title="Use SQLite", what="Chose SQLite", why="One file", impact="Easy backups",
            category="decision", details="Postgres was the alternative", journey_id=journey["id"],
        )  # fmt: skip
        sparse = await c.call("memory_save", title="Bare decision", what="Just this", category="decision")
        return {
            "adr": await c.call("draft_adr", memory_id=decision["id"][:8]),
            "sparse": await c.call("draft_adr", memory_id=sparse["id"]),
            "adr_missing": await c.error("draft_adr", memory_id="00000000-0000-0000-0000-000000000000"),
            "blog": await c.call("draft_blog", journey_id=journey["id"][:8]),
            "project_blog": await c.call("draft_blog", project="widget"),
            "neither": await c.error("draft_blog"),
        }

    out = arcane.run(scenario)
    adr = out["adr"]["brief"]
    for section in ("# ADR: Use SQLite", "## Context\nChose SQLite", "## Decision\nOne file", "Easy backups"):
        assert section in adr
    assert "Postgres was the alternative" in adr
    assert "None" not in out["sparse"]["brief"]
    assert "not found" in out["adr_missing"].lower()
    blog = out["blog"]["brief"]
    assert "# Blog Brief: Pick a store" in blog
    assert "Compared options" in blog and "Use SQLite" in blog
    assert "Use SQLite" in out["project_blog"]["brief"]
    assert "journey_id or project" in out["neither"]
