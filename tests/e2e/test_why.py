"""E2E: ``arcane why`` lists the decisions behind a file or a commit.

Memories are saved through the real ``arcane mcp`` server inside a temp git repo,
so provenance stamps the commit; the real CLI then reads them back.
"""

from __future__ import annotations

import json
from typing import Any

from tests.e2e.conftest import Arcane, Client, git


def _commit(arcane: Arcane, name: str, text: str) -> str:
    path = arcane.repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(arcane.repo, "add", ".")
    git(arcane.repo, "commit", "-q", "-m", f"feat: {name}")
    return git(arcane.repo, "rev-parse", "HEAD").strip()


def _why(arcane: Arcane, *args: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(arcane.cli("why", *args, "--json").stdout)
    return out


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [e["title"] for e in entries]


def _seed(arcane: Arcane) -> tuple[str, str]:
    first = _commit(arcane, "src/cache.py", "cache one\n")

    async def at_first(c: Client) -> None:
        await c.call(
            "memory_save",
            title="Use memcached",
            what="Chose memcached",
            why="Simple",
            category="decision",
            related_files=[str(arcane.repo / "src/cache.py")],
        )
        new = await c.call("memory_search", query="memcached")
        await c.call(
            "memory_save",
            title="Use redis",
            what="Chose redis",
            why="Persistence",
            category="decision",
            related_files=["src/cache.py"],
            supersedes=new[0]["id"],
        )
        await c.call(
            "memory_save",
            title="Cache suffix",
            what="Not the file",
            category="decision",
            related_files=["src/cache.pyc", "other/xcache.py"],
        )
        await c.call(
            "memory_save",
            title="Cache elsewhere",
            what="Other project",
            category="decision",
            project="gadget",
            related_files=["src/cache.py"],
        )
        await c.call(
            "memory_save",
            title="Cache insight",
            what="A learning, not a decision",
            category="learning",
            related_files=["src/cache.py"],
        )

    arcane.run(at_first)
    second = _commit(arcane, "src/cache.py", "cache two\n")

    async def at_second(c: Client) -> None:
        await c.call(
            "memory_save",
            title="Evict by TTL",
            what="Entries expire",
            why="Bounded size",
            category="bug",
            related_files=["src/ttl.py"],
        )

    arcane.run(at_second)
    return first, second


def test_why_file_lists_current_then_replaced(arcane: Arcane) -> None:
    _seed(arcane)

    out = _why(arcane, "src/cache.py")
    assert out["kind"] == "file" and out["files"] == ["src/cache.py"]
    assert _ids(out["memories"]) == ["Use redis"]
    assert out["memories"][0]["why"] == "Persistence"
    assert out["memories"][0]["project"] == "widget"
    assert _ids(out["superseded"]) == ["Use memcached"]
    assert out["superseded"][0]["superseded_by"]["id"] == out["memories"][0]["id"]
    # An absolute path under the repo means the same file.
    assert _why(arcane, str(arcane.repo / "src/cache.py")) == {**out, "target": str(arcane.repo / "src/cache.py")}

    everywhere = _why(arcane, "src/cache.py", "--all")
    assert sorted(_ids(everywhere["memories"])) == ["Cache elsewhere", "Use redis"]

    text = arcane.cli("why", "src/cache.py").stdout
    assert text.index("Use redis") < text.index("Replaced:") < text.index("Use memcached")
    assert "Replaced by" in text


def test_why_matches_on_a_slash_boundary_only(arcane: Arcane) -> None:
    _seed(arcane)

    assert _why(arcane, "ache.py")["memories"] == []  # "ache.py" ends "src/cache.py" but not at a "/"
    assert _why(arcane, "src/cache.p")["memories"] == []
    empty = arcane.cli("why", "src/nothing.py").stdout
    assert "No decisions or bugs found" in empty


def test_why_commit_lists_its_memories_then_file_decisions(arcane: Arcane) -> None:
    first, second = _seed(arcane)

    out = _why(arcane, second[:8])
    assert out["kind"] == "commit" and out["commit"] == second
    assert out["files"] == ["src/cache.py"]
    assert [(m["title"], m["via"]) for m in out["memories"]] == [("Evict by TTL", "commit"), ("Use redis", "file")]
    assert _ids(out["superseded"]) == ["Use memcached"]

    # Memories saved at the first commit match by their stamped SHA, whatever their category.
    at_first = _why(arcane, first)
    via_commit = {m["title"] for m in at_first["memories"] if m["via"] == "commit"}
    assert via_commit == {"Use redis", "Cache suffix", "Cache insight"}
    assert [m["title"] for m in at_first["memories"]].count("Use redis") == 1


def test_why_rejects_an_unknown_commit(arcane: Arcane) -> None:
    _seed(arcane)

    bad = arcane.cli("why", "deadbeef1", check=False)
    assert bad.returncode != 0
    assert "not a commit" in bad.stderr
