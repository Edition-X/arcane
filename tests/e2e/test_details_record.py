"""E2E: memory_details returns the whole record, and related_files is indexed and returned.

The real ``arcane mcp`` server and CLI run against a temp store. Only Ollama is
faked, for the one test that needs vectors.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client


def _cli(arcane: Arcane, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("core"), capture_output=True, text=True, check=False
    )


def test_memory_details_returns_the_whole_record(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        journey = await c.call("journey_start", title="Cache rollout")
        old = await c.call("memory_save", title="Use memcached", what="Chose memcached", why="Simple")
        new = await c.call(
            "memory_save",
            title="Use redis",
            what="Chose redis for sessions",
            why="Persistence",
            impact="Ops runs a redis cluster",
            category="decision",
            tags=["cache"],
            related_files=["src/cache.py", "docs/cache.md"],
            details="Options considered: memcached, redis",
            journey_id=journey["id"],
            supersedes=old["id"],
        )
        # Saved again under a second journey, the memory belongs to both.
        second = await c.call("journey_start", title="Cache follow-up")
        await c.call("memory_save", title="Use redis", what="Chose redis for sessions", journey_id=second["id"])
        return {
            "journey": journey,
            "old": old,
            "new": new,
            "record": await c.call("memory_details", memory_id=new["id"][:8]),
            "replaced": await c.call("memory_details", memory_id=old["id"]),
        }

    out = arcane.run(scenario)
    record = out["record"]
    assert record["memory_id"] == out["new"]["id"]
    assert (record["what"], record["why"], record["impact"]) == (
        "Chose redis for sessions",
        "Persistence",
        "Ops runs a redis cluster",
    )
    assert record["related_files"] == ["src/cache.py", "docs/cache.md"]
    assert [j["title"] for j in record["journeys"]] == ["Cache rollout", "Cache follow-up"]
    assert record["journeys"][0]["id"] == out["journey"]["id"]
    assert [m["id"] for m in record["supersedes"]] == [out["old"]["id"]]
    assert record["body"] == "Options considered: memcached, redis"
    assert record["has_details"] is True
    assert record["provenance"]["branch"] == "main"
    assert out["replaced"]["superseded_by"]["id"] == out["new"]["id"]


def test_memory_details_works_for_a_memory_with_no_details_row(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        saved = await c.call("memory_save", title="Bare note", what="Only a what", related_files=["a/b.py"])
        return {
            "record": await c.call("memory_details", memory_id=saved["id"]),
            "missing": await c.error("memory_details", memory_id="ffffffff"),
        }

    out = arcane.run(scenario)
    assert out["record"]["what"] == "Only a what"
    assert out["record"]["related_files"] == ["a/b.py"]
    assert out["record"]["body"] == ""
    assert out["record"]["has_details"] is False
    assert out["record"]["journeys"] == []
    assert "not found" in out["missing"].lower()


def test_cli_details_prints_the_same_record(arcane: Arcane) -> None:
    async def seed(c: Client) -> dict[str, Any]:
        journey = await c.call("journey_start", title="Cache rollout")
        old = await c.call("memory_save", title="Use memcached", what="Chose memcached")
        full = await c.call(
            "memory_save",
            title="Use redis",
            what="Chose redis",
            why="Persistence",
            impact="Ops runs redis",
            related_files=["src/cache.py"],
            details="Options considered: memcached",
            journey_id=journey["id"],
            supersedes=old["id"],
        )
        bare = await c.call("memory_save", title="Bare note", what="Only a what")
        record = await c.call("memory_details", memory_id=full["id"])
        return {"full": full, "bare": bare, "record": record}

    ids = arcane.run(seed)
    text = _cli(arcane, "details", ids["full"]["id"][:8]).stdout
    for expected in (
        "Use redis",
        "What: Chose redis",
        "Why: Persistence",
        "Impact: Ops runs redis",
        "Files: src/cache.py",
        "Journey: Cache rollout",
        "Replaces: Use memcached",
        "memcached",
    ):
        assert expected in text
    assert json.loads(_cli(arcane, "details", ids["full"]["id"], "--json").stdout) == ids["record"]
    bare = _cli(arcane, "details", ids["bare"]["id"])
    assert bare.returncode == 0 and "Details: none" in bare.stdout
    missing = _cli(arcane, "details", "ffffffff")
    assert missing.returncode != 0 and "not found" in missing.stderr.lower()
