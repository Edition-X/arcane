"""E2E: the server records what lookups return, and ``analyze usage`` reports on it."""

from __future__ import annotations

import subprocess
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client


def _cli(arcane: Arcane, *args: str) -> str:
    result = subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True, check=True
    )
    return result.stdout


def test_lookups_are_recorded_with_what_they_returned(arcane: Arcane) -> None:
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"

    async def scenario(c: Client) -> dict[str, Any]:
        first = await c.call("memory_save", title="Pin the runner image", what="Pinned runner image", details="d")
        second = await c.call("memory_save", title="Runner disk fills", what="Docker images fill the runner disk")
        journey = await c.call("journey_start", title="Runner flakes")
        await c.call("ingest_git", max_count=10)
        await c.call("memory_search", query="runner")
        await c.call("memory_search", query="kubernetes upgrade")
        await c.call("memory_search", query=f"leaked {token}")
        await c.call("memory_context")
        await c.call("memory_details", memory_id=first["id"][:8])
        await c.call("memory_update", memory_id=second["id"][:8], why="Images are never pruned")
        await c.call("journey_show", journey_id=journey["id"][:8])
        await c.call("artifact_search", query="change")
        await c.session.read_resource("arcane://context/widget")  # type: ignore[arg-type]
        await c.error("memory_details", memory_id="00000000-0000-0000-0000-000000000000")
        return {"first": first["id"], "second": second["id"], "journey": journey["id"]}

    ids = arcane.run(scenario, client_name="Claude Code")
    rows = arcane.sql(
        "SELECT tool, client, project, org, query, result_count, is_error, session_id FROM retrievals ORDER BY rowid"
    )
    tools = [r[0] for r in rows]
    assert tools == [
        "memory_search",
        "memory_search",
        "memory_search",
        "memory_context",
        "memory_details",
        "memory_update",
        "journey_show",
        "artifact_search",
        "resource_context",
        "memory_details",
    ]
    assert {r[1] for r in rows} == {"claude-code"}
    assert {(r[2], r[3]) for r in rows} == {("widget", "acme")}
    assert len({r[7] for r in rows}) == 1  # one server process is one session

    runner, empty, leaked = rows[0], rows[1], rows[2]
    assert runner[4] == "runner" and runner[5] == 2
    assert empty[4] == "kubernetes upgrade" and empty[5] == 0
    keyword = dict(arcane.sql("SELECT query, keyword_matches FROM retrievals WHERE tool = 'memory_search'"))
    assert keyword["runner"] == 2 and keyword["kubernetes upgrade"] == 0
    assert token not in leaked[4] and "[REDACTED]" in leaked[4]
    assert rows[-1][6] == 1 and rows[-1][5] == 0  # failed lookups are kept, with no hits

    def hits(tool: str) -> list[tuple[str, str]]:
        return arcane.sql(
            "SELECT h.entity_type, h.entity_id FROM retrieval_hits h JOIN retrievals r ON r.id = h.retrieval_id "
            "WHERE r.tool = ? ORDER BY r.rowid, h.rank",
            (tool,),
        )

    assert {h[1] for h in hits("memory_search")} == {ids["first"], ids["second"]}
    assert hits("memory_details") == [("memory", ids["first"])]
    assert hits("memory_update") == [("memory", ids["second"])]  # full ID, though the agent sent a prefix
    assert hits("journey_show") == [("journey", ids["journey"])]
    assert len(hits("artifact_search")) == 2
    assert {h[1] for h in hits("resource_context")} == {ids["first"], ids["second"]}


def test_saves_and_admin_tools_are_not_recorded(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        saved = await c.call("memory_save", title="Not a lookup", what="w")
        await c.call("journey_start", title="Nor this")
        await c.call("analyze", plugin_name="health")
        await c.call("memory_delete", memory_id=saved["id"])

    arcane.run(scenario)
    assert arcane.sql("SELECT count(*) FROM retrievals")[0][0] == 0


def test_usage_report_shows_agents_gaps_and_follow_through(arcane: Arcane) -> None:
    async def claude(c: Client) -> str:
        saved = await c.call("memory_save", title="Pin the runner image", what="Pinned runner image", details="d")
        await c.call("memory_search", query="runner image")
        await c.call("memory_details", memory_id=saved["id"])
        await c.call("memory_search", query="kubernetes upgrade")
        await c.call("memory_search", query="Kubernetes upgrade")
        # Returns the runner memory on the word "runner", but no memory holds both key words.
        await c.call("memory_search", query="runner kubernetes")
        return str(saved["id"])

    async def codex(c: Client) -> dict[str, Any]:
        await c.call("memory_search", query="runner")
        return {
            "analyze": await c.call("analyze", plugin_name="usage"),
            "context": await c.call("memory_context"),
        }

    memory_id = arcane.run(claude, client_name="Claude Code")
    out = arcane.run(codex, client_name="codex-mcp-client")

    assert out["analyze"]["insights_created"] == 2
    surfaced = {i["type"] for i in out["context"]["insights"]}
    assert {"usage", "usage_gaps"} <= surfaced

    report = _cli(arcane, "analyze", "usage")
    assert "Usage: 7 lookups in 30 days, 60% of searches were possible gaps" in report
    assert "claude-code: 5 lookups, 1 sessions" in report
    assert "codex-mcp-client: 2 lookups, 1 sessions" in report
    assert "Searches with text: 5, possible gaps: 3 (60%; 2 returned nothing" in report
    assert "opening or updating a returned memory: 1 of 4 (25%)" in report
    # Returned by three searches and the context load, and opened once.
    assert f"5x  Pin the runner image (widget) [{memory_id[:8]}]" in report
    assert '2x  "kubernetes upgrade" (widget, nothing returned)' in report
    assert '1x  "runner kubernetes" (widget)' in report
    assert "never recalled" not in report  # under 30 days of history


def test_memories_nobody_recalls_are_reported_once_there_is_history(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await c.call("memory_save", title="Used often", what="recalled memory", project="widget")
        await c.call("memory_save", title="Forgotten", what="nobody asks", project="gadget")
        await c.call("memory_search", query="recalled")

    arcane.run(scenario)
    arcane.sql("UPDATE memories SET created_at = datetime('now', '-60 days')")
    arcane.sql("UPDATE retrievals SET created_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-40 days')")

    report = _cli(arcane, "analyze", "usage", "--days", "90")
    assert "1 memories never recalled (50%)" in report
    assert "  gadget: 1" in report


def test_old_lookups_are_pruned_when_the_server_starts(arcane: Arcane) -> None:
    async def lookups(c: Client) -> None:
        await c.call("memory_save", title="Kept", what="w")
        await c.call("memory_search", query="kept")
        await c.call("memory_search", query="w")

    arcane.run(lookups)
    arcane.sql(
        "UPDATE retrievals SET created_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-200 days') "
        "WHERE query = 'kept'"
    )

    async def nothing(c: Client) -> None:
        pass

    arcane.run(nothing)
    assert [r[0] for r in arcane.sql("SELECT query FROM retrievals")] == ["w"]
    orphans = arcane.sql("SELECT count(*) FROM retrieval_hits WHERE retrieval_id NOT IN (SELECT id FROM retrievals)")
    assert orphans[0][0] == 0


def test_recording_and_query_text_can_be_turned_off(arcane: Arcane) -> None:
    config = arcane.home / "config.yaml"
    base = config.read_text(encoding="utf-8")

    async def search(c: Client) -> None:
        await c.call("memory_search", query="private topic")

    config.write_text(base + "usage:\n  log_queries: false\n", encoding="utf-8")
    arcane.run(search)
    assert arcane.sql("SELECT tool, query FROM retrievals") == [("memory_search", None)]

    config.write_text(base + "usage:\n  enabled: false\n", encoding="utf-8")
    arcane.run(search)
    assert arcane.sql("SELECT count(*) FROM retrievals")[0][0] == 1
