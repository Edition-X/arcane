"""E2E: decision journeys through the MCP server."""

from __future__ import annotations

from typing import Any

from tests.e2e.conftest import Arcane, Client


def test_journey_lifecycle_links_memories_and_commits(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        journey = await c.call("journey_start", title="Pick a store", linear_issue_id="ARC-1")
        jid = journey["id"]
        # Agents pass short prefixes; links must still land on the full ID.
        await c.call("journey_update", journey_id=jid[:8], summary="Compared SQLite and Postgres")
        memory = await c.call("memory_save", title="Use SQLite", what="Chose SQLite", journey_id=jid[:12])
        ingest = await c.call("ingest_git", max_count=10, journey_id=jid[:12])
        out: dict[str, Any] = {"journey": journey, "memory": memory, "ingest": ingest}
        out["active"] = await c.call("journey_list", status="active")
        out["show"] = await c.call("journey_show", journey_id=jid[:8])
        out["complete"] = await c.call("journey_complete", journey_id=jid[:8], summary="SQLite it is")
        out["shown_done"] = await c.call("journey_show", journey_id=jid)
        out["completed"] = await c.call("journey_list", status="completed")
        return out

    out = arcane.run(scenario)
    jid = out["journey"]["id"]
    assert out["journey"]["project"] == "widget"
    assert [j["id"] for j in out["active"]] == [jid]
    show = out["show"]
    assert show["status"] == "active"
    assert show["summary"] == "Compared SQLite and Postgres"
    assert [m["memory_id"] for m in show["linked_memories"]] == [out["memory"]["id"]]
    assert out["ingest"]["ingested"] == 2
    assert sorted(a["title"] for a in show["linked_artifacts"]) == ["feat: change one", "feat: change two"]
    assert [e["event_type"] for e in show["events"]] == ["updated"]

    assert out["complete"]["completed"] is True
    done = out["shown_done"]
    assert done["status"] == "completed"
    assert done["summary"] == "SQLite it is"
    assert done["completed_at"]
    assert [e["event_type"] for e in done["events"]][-1] == "completed"
    assert [j["id"] for j in out["completed"]] == [jid]


def test_abandon_and_delete_keep_linked_memories(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        dead_end = await c.call("journey_start", title="Try Postgres")
        junk = await c.call("journey_start", title="Test junk")
        memory = await c.call("memory_save", title="Postgres too heavy", what="Needs a server", journey_id=junk["id"])
        return {
            "abandon": await c.call("journey_abandon", journey_id=dead_end["id"][:8], reason="Too heavy"),
            "abandoned": await c.call("journey_show", journey_id=dead_end["id"]),
            "delete": await c.call("journey_delete", journey_id=junk["id"][:8]),
            "deleted": await c.error("journey_show", journey_id=junk["id"]),
            "memory": await c.call("memory_search", query="Postgres heavy"),
            "memory_id": memory["id"],
        }

    out = arcane.run(scenario)
    assert out["abandoned"]["status"] == "abandoned"
    assert "Too heavy" in out["abandoned"]["summary"]
    assert "not found" in out["deleted"].lower()
    assert [m["id"] for m in out["memory"]] == [out["memory_id"]]
    assert arcane.sql("SELECT count(*) FROM relationships")[0][0] == 0


def test_missing_journeys_are_errors(arcane: Arcane) -> None:
    missing = "00000000-0000-0000-0000-000000000000"

    async def scenario(c: Client) -> tuple[list[str], dict[str, Any]]:
        errors = [
            await c.error("journey_update", journey_id=missing, summary="x"),
            await c.error("journey_complete", journey_id=missing),
            await c.error("journey_abandon", journey_id=missing),
            await c.error("journey_show", journey_id=missing),
            await c.error("journey_delete", journey_id=missing),
        ]
        # A bad journey link must not lose the memory: it saves and says why it is unlinked.
        return errors, await c.call("memory_save", title="t", what="w", journey_id="short")

    errors, saved = arcane.run(scenario)
    assert all("not found" in e.lower() for e in errors), errors
    assert saved["warnings"][0].startswith("journey_not_linked")
    assert "at least 8 characters" in saved["warnings"][0]


def test_idle_means_no_update_for_14_days_everywhere(arcane: Arcane) -> None:
    async def start(c: Client) -> tuple[str, str, str]:
        idle = await c.call("journey_start", title="Forgotten spike")
        revived = await c.call("journey_start", title="Old but active")
        fresh = await c.call("journey_start", title="Current work")
        return idle["id"], revived["id"], fresh["id"]

    idle, revived, fresh = arcane.run(start)
    # Untouched for 20 days: idle, though younger than the old 30-day started_at rule.
    arcane.sql(
        "UPDATE journeys SET started_at = datetime('now', '-20 days'), updated_at = datetime('now', '-20 days') "
        "WHERE id = ?",
        (idle,),
    )
    # Started long ago but updated yesterday: not idle.
    arcane.sql(
        "UPDATE journeys SET started_at = datetime('now', '-90 days'), updated_at = datetime('now', '-1 days') "
        "WHERE id = ?",
        (revived,),
    )

    async def check(c: Client) -> dict[str, Any]:
        return {
            "list": await c.call("journey_list"),
            "context": await c.call("memory_context"),
            "minimal": await c.call("memory_context", detail="minimal"),
            "health": await c.call("analyze", plugin_name="health"),
            "insights": await c.call("insights"),
        }

    out = arcane.run(check)
    flags = {j["id"]: j.get("stale", False) for j in out["list"]}
    assert flags == {idle: True, revived: False, fresh: False}
    assert [j["id"] for j in out["context"]["stale_journeys"]] == [idle]
    assert "idle >14 days" in out["context"]["message"]
    assert "stale_journeys" not in out["minimal"]
    assert "1 journey(s) stuck in active" in {i["title"] for i in out["insights"]}
