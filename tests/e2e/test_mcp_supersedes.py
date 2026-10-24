"""E2E: marking a memory as replaced by a newer one, and how recall treats it."""

from __future__ import annotations

import subprocess
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client


def test_a_replaced_decision_is_labelled_ranked_lower_and_left_out_of_context(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        old = await c.call(
            "memory_save", title="Tag runner images", what="Runner images are pulled by tag",
            why="Simple to read", category="decision", details="Tags are human readable",
        )  # fmt: skip
        new = await c.call(
            "memory_save", title="Pin runner images by digest", what="Runner images are pulled by digest",
            why="Tags moved under us twice", category="decision", details="Digests are immutable",
            supersedes=old["id"][:8],
        )  # fmt: skip
        return {
            "old": old["id"],
            "new": new,
            "search": await c.call("memory_search", query="runner images"),
            "minimal": await c.call("memory_search", query="runner images", detail="minimal"),
            "context": await c.call("memory_context"),
            "new_details": await c.call("memory_details", memory_id=new["id"]),
            "old_details": await c.call("memory_details", memory_id=old["id"]),
        }

    out = arcane.run(scenario)
    old_id, new_id = out["old"], out["new"]["id"]
    assert out["new"]["warnings"] == []
    rows = arcane.sql("SELECT source_id, target_id, relation FROM relationships")
    assert rows == [(new_id, old_id, "supersedes")]

    assert [r["id"] for r in out["search"]] == [new_id, old_id]
    old_hit = out["search"][1]
    assert old_hit["superseded_by"]["id"] == new_id
    assert old_hit["superseded_by"]["title"] == "Pin runner images by digest"
    assert "superseded_by" not in out["search"][0]
    assert out["minimal"][1]["superseded_by"]["id"] == new_id

    assert [m["id"] for m in out["context"]["memories"]] == [new_id]
    assert [m["id"] for m in out["new_details"]["supersedes"]] == [old_id]
    assert out["old_details"]["superseded_by"]["id"] == new_id


def test_bad_supersedes_references_warn_and_still_save(arcane: Arcane) -> None:
    async def scenario(c: Client) -> tuple[dict[str, Any], dict[str, Any]]:
        short = await c.call("memory_save", title="A", what="a", supersedes="abc")
        missing = await c.call("memory_save", title="B", what="b", supersedes="00000000-0000-0000-0000-000000000000")
        return short, missing

    short, missing = arcane.run(scenario)
    assert short["warnings"][0].startswith("supersedes_not_linked")
    assert missing["warnings"][0].startswith("supersedes_not_found")
    assert arcane.sql("SELECT count(*) FROM memories")[0][0] == 2
    assert arcane.sql("SELECT count(*) FROM relationships")[0][0] == 0


def test_update_and_same_title_saves_can_mark_a_replacement(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        first = await c.call("memory_save", title="Old fix", what="Restart the runner", category="bug")
        second = await c.call("memory_save", title="Real fix", what="Prune Docker images", category="bug")
        third = await c.call("memory_save", title="Older idea", what="Bigger disk", category="decision")
        return {
            "ids": (first["id"], second["id"], third["id"]),
            "update": await c.call("memory_update", memory_id=second["id"][:8], supersedes=first["id"][:8]),
            "again": await c.call("memory_update", memory_id=second["id"], supersedes=first["id"]),
            "self": await c.call("memory_update", memory_id=second["id"], supersedes=second["id"]),
            "unknown": await c.error(
                "memory_update", memory_id=second["id"], supersedes="00000000-0000-0000-0000-000000000000"
            ),
            # Same title in the same project merges into the existing memory, link included.
            "merge": await c.call(
                "memory_save",
                title="Real fix",
                what="Prune Docker images nightly",
                category="bug",
                supersedes=third["id"],
            ),  # fmt: skip
        }

    out = arcane.run(scenario)
    first, second, third = out["ids"]
    assert out["update"]["updated"] is True and out["merge"]["action"] == "updated"
    assert "Superseded memory not found" in out["unknown"]
    links = set(arcane.sql("SELECT source_id, target_id FROM relationships WHERE relation = 'supersedes'"))
    assert links == {(second, first), (second, third)}


def test_cli_save_marks_a_replacement_and_usage_counts_replaced_hits(arcane: Arcane) -> None:
    async def save_old(c: Client) -> str:
        return str((await c.call("memory_save", title="Nightly at 02:00", what="Backups run at night"))["id"])

    old_id = arcane.run(save_old)
    env = arcane.env("full")
    saved = subprocess.run(
        [ARCANE, "save", "--title", "Backups at 13:00", "--what", "Backups run midday", "--supersedes", old_id[:8]],
        cwd=arcane.repo, env=env, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "Warning" not in saved

    async def search(c: Client) -> list[dict[str, Any]]:
        return list(await c.call("memory_search", query="backups"))

    hits = arcane.run(search)
    assert hits[-1]["id"] == old_id and "superseded_by" in hits[-1]
    report = subprocess.run(
        [ARCANE, "analyze", "usage"], cwd=arcane.repo, env=env, capture_output=True, text=True, check=True
    ).stdout
    assert "Lookups that returned a replaced (superseded) memory: 1 (1 hits)." in report
