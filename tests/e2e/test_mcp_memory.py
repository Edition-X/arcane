"""E2E: saving, finding, changing and removing memories through the MCP server."""

from __future__ import annotations

from typing import Any

from tests.e2e.conftest import Arcane, Client


def test_memory_lifecycle(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        saved = await c.call(
            "memory_save",
            title="Use SQLite for the store",
            what="Chose SQLite with FTS5 for memories",
            why="One file, no server",
            impact="Backups are a file copy",
            category="decision",
            tags=["storage"],
            details="Options: SQLite, Postgres",
        )
        mid = saved["id"]
        out: dict[str, Any] = {"saved": saved}
        for detail in ("minimal", "standard", "full"):
            out[f"search_{detail}"] = await c.call("memory_search", query="SQLite", detail=detail)
        out["details"] = await c.call("memory_details", memory_id=mid[:8])
        out["update"] = await c.call(
            "memory_update",
            memory_id=mid[:8],
            what="Chose SQLite again",
            tags=["storage", "sqlite"],
            details_append="Revisited",
        )
        out["after_update"] = await c.call("memory_search", query="SQLite", detail="full")
        out["details_after"] = await c.call("memory_details", memory_id=mid)
        out["delete"] = await c.call("memory_delete", memory_id=mid[:8])
        out["details_gone"] = await c.error("memory_details", memory_id=mid)
        out["delete_again"] = await c.error("memory_delete", memory_id=mid)
        out["update_gone"] = await c.error("memory_update", memory_id=mid, what="x")
        out["search_gone"] = await c.call("memory_search", query="SQLite")
        return out

    out = arcane.run(scenario)

    assert out["saved"]["scope"] == {"org": "acme", "project": "widget"}
    assert out["saved"]["warnings"] == []
    assert set(out["search_minimal"][0]) == {"id", "title", "category", "score"}
    standard = out["search_standard"][0]
    assert standard["what"] == "Chose SQLite with FTS5 for memories"
    assert standard["has_details"] is True
    assert "why" not in standard
    assert out["search_full"][0]["why"] == "One file, no server"
    assert out["search_full"][0]["impact"] == "Backups are a file copy"
    assert out["details"]["body"] == "Options: SQLite, Postgres"

    assert out["update"]["updated"] is True
    updated = out["after_update"][0]
    assert updated["what"] == "Chose SQLite again"
    assert updated["tags"] == ["storage", "sqlite"]
    assert updated["why"] == "One file, no server"
    assert "Options: SQLite, Postgres" in out["details_after"]["body"]
    assert "Revisited" in out["details_after"]["body"]

    assert out["delete"]["deleted"] is True
    assert "no details found" in out["details_gone"].lower()
    assert "not found" in out["delete_again"].lower()
    assert "not found" in out["update_gone"].lower()
    assert out["search_gone"] == []


def test_source_is_stamped_from_the_client_unless_given(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[str, str]:
        stamped = await c.call("memory_save", title="Stamped", what="from the handshake")
        explicit = await c.call("memory_save", title="Explicit", what="caller says", source="my-script")
        return stamped["id"], explicit["id"]

    stamped, explicit = arcane.run(scenario, client_name="Claude Code")
    rows = dict(arcane.sql("SELECT id, source FROM memories"))
    assert rows[stamped] == "claude-code"
    assert rows[explicit] == "my-script"


def test_save_scope_rules(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        return {
            "worktree": await c.call("memory_save", title="A", what="a", project="widget-inf613"),
            "other": await c.call("memory_save", title="B", what="b", project="Gadget"),
            "blank": await c.call("memory_save", title="C", what="c", project=""),
            "org": await c.call("memory_save", title="D", what="d", scope="org"),
            "global": await c.call("memory_save", title="E", what="e", scope="global"),
            "org_with_project": await c.call("memory_save", title="F", what="f", scope="org", project="widget"),
            "global_with_org": await c.call("memory_save", title="G", what="g", scope="global", org="acme"),
        }

    out = arcane.run(scenario)
    assert out["worktree"]["scope"] == {"org": "acme", "project": "widget"}
    assert out["other"]["scope"] == {"org": "acme", "project": "gadget"}
    assert out["blank"]["warnings"][0].startswith("empty_project")
    assert out["org"]["scope"] == {"org": "acme", "project": ""}
    assert out["org"]["warnings"] == []
    assert out["global"]["scope"]["org"] == "global"
    # A scope that drops an explicit project or org says so instead of discarding it silently.
    assert out["org_with_project"]["scope"] == {"org": "acme", "project": ""}
    assert out["org_with_project"]["warnings"][0].startswith("project_ignored")
    assert out["global_with_org"]["scope"]["org"] == "global"
    assert out["global_with_org"]["warnings"][0].startswith("org_ignored")


def test_context_layers_and_detail_levels(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await c.call("memory_save", title="Widget decision", what="project layer", why="w", category="decision")
        await c.call("memory_save", title="Acme convention", what="org layer", scope="org")
        await c.call("memory_save", title="Universal habit", what="global layer", scope="global")
        await c.call("memory_save", title="Gadget note", what="another project", project="gadget")
        return {
            "standard": await c.call("memory_context"),
            "minimal": await c.call("memory_context", detail="minimal"),
            "full": await c.call("memory_context", detail="full"),
            "project_only": await c.call("memory_context", scope="project"),
            "no_global": await c.call("memory_context", include_global=False),
            "query": await c.call("memory_context", query="convention"),
            "search_no_org": await c.call("memory_search", query="layer", include_org=False, include_global=False),
        }

    out = arcane.run(scenario)

    def titles(payload: dict[str, Any]) -> set[str]:
        return {m["title"] for m in payload["memories"]}

    assert titles(out["standard"]) == {"Widget decision", "Acme convention", "Universal habit"}
    assert titles(out["project_only"]) == {"Widget decision"}
    assert titles(out["no_global"]) == {"Widget decision", "Acme convention"}
    assert "Acme convention" in titles(out["query"])
    assert {m["title"] for m in out["search_no_org"]} == {"Widget decision"}
    assert all(set(m) == {"id", "title", "category"} for m in out["minimal"]["memories"])
    full = next(m for m in out["full"]["memories"] if m["title"] == "Widget decision")
    assert full["why"] == "w"


def test_secrets_are_redacted_before_they_are_stored(arcane: Arcane) -> None:
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"

    async def scenario(c: Client) -> dict[str, Any]:
        saved = await c.call(
            "memory_save",
            title="CI token rotated",
            what=f"New token is {token}",
            details="password=hunter2hunter2 was the old one",
        )
        return {
            "search": await c.call("memory_search", query="token rotated"),
            "details": await c.call("memory_details", memory_id=saved["id"]),
            "file": saved["file_path"],
        }

    out = arcane.run(scenario)
    assert token not in out["search"][0]["what"]
    assert "[REDACTED]" in out["search"][0]["what"]
    assert "hunter2hunter2" not in out["details"]["body"]
    stored = " ".join(str(v) for row in arcane.sql("SELECT what, why, impact FROM memories") for v in row)
    stored += " ".join(row[0] for row in arcane.sql("SELECT body FROM memory_details"))
    assert token not in stored and "hunter2hunter2" not in stored
    vault_text = open(out["file"], encoding="utf-8").read()
    assert token not in vault_text and "hunter2hunter2" not in vault_text
