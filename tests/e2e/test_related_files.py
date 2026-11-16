"""E2E: related_files is indexed for keyword search and returned in search hits.

The real ``arcane mcp`` server runs against a temp store. Only Ollama is faked,
for the one test that needs vectors.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from tests.e2e.conftest import Arcane, Client
from tests.e2e.test_details_search import FakeOllama, _titles, ollama  # noqa: F401  (ollama is a fixture)

PATH = "src/zephyr/quux_handler.py"


def test_a_path_in_related_files_finds_the_memory_and_the_hit_lists_it(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        for n in range(6):
            await c.call("memory_save", title=f"Other {n}", what="Something else entirely", related_files=["x/y.py"])
        # The path's words appear in no other field of this memory.
        await c.call(
            "memory_save", title="Handler rewrite", what="Reworked the handler", related_files=[PATH, "docs/other.md"]
        )
        return {
            "by_path": await c.call("memory_search", query=PATH),
            "by_second_path": await c.call("memory_search", query="docs/other.md"),
            "full": await c.call("memory_search", query=PATH, detail="full"),
            "minimal": await c.call("memory_search", query=PATH, detail="minimal"),
            "plain": await c.call("memory_search", query="entirely", limit=1),
        }

    out = arcane.run(scenario)
    assert _titles(out["by_path"]) == ["Handler rewrite"]
    assert _titles(out["by_second_path"]) == ["Handler rewrite"]
    assert out["by_path"][0]["related_files"] == [PATH, "docs/other.md"]
    assert out["full"][0]["related_files"] == [PATH, "docs/other.md"]
    assert "related_files" not in out["minimal"][0]
    assert out["plain"][0]["related_files"] == ["x/y.py"]


def test_a_full_path_query_earns_the_whole_query_bonus(arcane: Arcane, ollama: FakeOllama) -> None:  # noqa: F811
    async def scenario(c: Client) -> list[dict[str, Any]]:
        # The path is in related_files only, so the memory's vector is far from the query.
        await c.call(
            "memory_save",
            title="Handler rewrite",
            what="Reworked the handler. " + "filler text about other things " * 20,
            related_files=[PATH],
        )
        for n in range(1, 21):
            await c.call("memory_save", title=f"Unrelated {n}", what="item " * n)
        return await c.call("memory_search", query=PATH, limit=3)

    # Every key word of the query is in the memory; "py" and "src" are inside one path term, not dropped words.
    assert _titles(arcane.run(scenario))[0] == "Handler rewrite"


def test_updating_a_memory_keeps_its_files_in_the_index(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        saved = await c.call("memory_save", title="Handler rewrite", what="Reworked", related_files=[PATH])
        await c.call("memory_update", memory_id=saved["id"], what="Reworked again", details_append="More notes")
        found = await c.call("memory_search", query=PATH)
        await c.call("memory_delete", memory_id=saved["id"])
        return {"found": found, "gone": await c.call("memory_search", query=PATH)}

    out = arcane.run(scenario)
    assert _titles(out["found"]) == ["Handler rewrite"]
    assert out["gone"]["results"] == []


def test_a_store_whose_index_has_details_but_no_files_is_upgraded_without_losing_memories(arcane: Arcane) -> None:
    async def seed(c: Client) -> None:
        await c.call(
            "memory_save", title="Handler rewrite", what="Reworked", related_files=[PATH], details="Notes here"
        )
        await c.call("memory_save", title="Queue layer", what="Added a queue")

    arcane.run(seed)
    # Put the store back as the details-search release left it: a details column, no related_files.
    conn = sqlite3.connect(arcane.home / "index.db")
    conn.executescript("""
        DROP TRIGGER memories_ai; DROP TRIGGER memories_au; DROP TRIGGER memories_ad;
        DROP TRIGGER memory_details_ai; DROP TRIGGER memory_details_au; DROP TRIGGER memory_details_ad;
        DROP TABLE memories_fts;
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            title, what, why, impact, tags, category, project, source, details, tokenize='porter unicode61'
        );
        INSERT INTO memories_fts(rowid, title, what, why, impact, tags, category, project, source, details)
            SELECT m.rowid, m.title, m.what, m.why, m.impact, m.tags, m.category, m.project, m.source, d.body
            FROM memories m LEFT JOIN memory_details d ON d.memory_id = m.id;
    """)
    conn.close()

    async def search(c: Client) -> dict[str, Any]:
        return {
            "path": await c.call("memory_search", query=PATH),
            "details": await c.call("memory_search", query="notes"),
        }

    first = arcane.run(search)
    assert _titles(first["path"]) == ["Handler rewrite"] and _titles(first["details"]) == ["Handler rewrite"]
    assert arcane.sql("SELECT title FROM memories ORDER BY rowid") == [("Handler rewrite",), ("Queue layer",)]
    index = arcane.sql("SELECT rowid, title, details, related_files FROM memories_fts ORDER BY rowid")
    assert index[0] == (1, "Handler rewrite", "Notes here", PATH)
    triggers = arcane.sql("SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name")

    assert arcane.run(search) == first  # a second start changes nothing
    assert arcane.sql("SELECT rowid, title, details, related_files FROM memories_fts ORDER BY rowid") == index
    assert arcane.sql("SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name") == triggers
