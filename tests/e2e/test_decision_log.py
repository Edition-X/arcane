"""E2E: ``arcane decisions`` over a store filled through the MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.e2e.conftest import Arcane, Client

DETAILS = """Context: why we looked.

## Options considered
- tags: simple, but they move
- digests: exact

Trade-offs:
Digests are unreadable.

Follow-up: roll out next week."""


def _fill(arcane: Arcane) -> dict[str, str]:
    async def scenario(c: Client) -> dict[str, str]:
        old = await c.call(
            "memory_save", title="Pin images by tag", what="Use tags", why="Easy", category="decision"
        )  # fmt: skip
        new = await c.call(
            "memory_save", title="Pin images by digest", what="Use digests, not tags",
            why="Tags moved under us twice", category="decision", details=DETAILS, supersedes=old["id"],
        )  # fmt: skip
        plain = await c.call(
            "memory_save", title="Plain decision", what="No details", why="Simple", category="decision",
            details="Context: only background, nothing about choices.",
        )  # fmt: skip
        long = await c.call(
            "memory_save", title="Long options", what="Many", why="Because", category="decision",
            details="Options:\n" + "word " * 600,
        )  # fmt: skip
        expired = await c.call("memory_save", title="Expired decision", what="Gone", category="decision")
        await c.call("memory_save", title="A bug", what="Not a decision", category="bug")
        other = await c.call(
            "memory_save", title="Other project decision", what="Elsewhere", category="decision",
            project="toybox", org="personal",
        )  # fmt: skip
        return {
            "old": old["id"], "new": new["id"], "plain": plain["id"], "long": long["id"],
            "expired": expired["id"], "other": other["id"],
        }  # fmt: skip

    ids = arcane.run(scenario)
    arcane.sql("UPDATE memories SET created_at = '2026-01-01T10:00:00+00:00' WHERE id = ?", (ids["old"],))
    arcane.sql("UPDATE memories SET created_at = '2026-02-01T10:00:00+00:00' WHERE id = ?", (ids["new"],))
    arcane.sql("UPDATE memories SET created_at = '2026-03-01T10:00:00+00:00' WHERE id = ?", (ids["plain"],))
    arcane.sql("UPDATE memories SET created_at = '2026-04-01T10:00:00+00:00' WHERE id = ?", (ids["long"],))
    arcane.sql(
        "UPDATE memories SET created_at = '2026-01-05T10:00:00+00:00', ttl_days = 1 WHERE id = ?", (ids["expired"],)
    )
    return ids


def test_log_lists_current_decisions_newest_first_then_replaced(arcane: Arcane) -> None:
    ids = _fill(arcane)
    out = arcane.cli("decisions").stdout

    assert out.startswith("# Decision log: acme/widget\n\n3 current · 1 replaced\n")
    titles = [line for line in out.splitlines() if line.startswith("### ")]
    assert titles == [
        f"### 2026-04-01 · Long options (`{ids['long'][:8]}`)",
        f"### 2026-03-01 · Plain decision (`{ids['plain'][:8]}`)",
        f"### 2026-02-01 · Pin images by digest (`{ids['new'][:8]}`)",
    ]
    assert "**What:** Use digests, not tags\n\n**Why:** Tags moved under us twice" in out
    assert "A bug" not in out and "Expired decision" not in out and "Other project decision" not in out

    replaced = out.split("## Replaced\n", 1)[1]
    assert replaced == (
        f"\n- 2026-01-01 · Pin images by tag (`{ids['old'][:8]}`) — replaced by `{ids['new'][:8]}` "
        "Pin images by digest (2026-02-01)\n"
    )
    assert "Pin images by tag" not in out.split("## Replaced\n", 1)[0]


def test_only_option_sections_of_details_appear_and_are_capped(arcane: Arcane) -> None:
    _fill(arcane)
    out = arcane.cli("decisions").stdout

    assert "**Options considered**\n\n> - tags: simple, but they move\n> - digests: exact" in out
    assert "**Trade-offs**\n\n> Digests are unreadable." in out
    assert "why we looked" not in out and "roll out next week" not in out  # other sections stay out
    assert "only background" not in out  # no matching section: details omitted

    long_section = out.split("**Options**\n\n> ", 1)[1].split("\n\n", 1)[0]
    assert len(long_section) <= 1201 and long_section.endswith("…")


def test_output_is_deterministic_and_written_only_with_out(arcane: Arcane, tmp_path: Path) -> None:
    _fill(arcane)
    first = arcane.cli("decisions").stdout
    assert arcane.cli("decisions").stdout == first
    assert not list(arcane.repo.glob("*.md"))

    target = tmp_path / "log.md"
    message = arcane.cli("decisions", "--out", str(target)).stdout
    assert "Wrote 3 decisions and 1 replaced" in message
    assert target.read_text(encoding="utf-8") == first


def test_json_format_and_scope_overrides(arcane: Arcane) -> None:
    ids = _fill(arcane)

    data: dict[str, Any] = json.loads(arcane.cli("decisions", "--format", "json").stdout)
    assert (data["org"], data["project"]) == ("acme", "widget")
    assert [d["id"] for d in data["decisions"]] == [ids["long"], ids["plain"], ids["new"]]
    [replaced] = data["replaced"]
    assert replaced["id"] == ids["old"] and replaced["replaced_by"]["id"] == ids["new"]
    assert data["decisions"][2]["options"][0]["label"] == "Options considered"

    toy = arcane.cli("decisions", "--project", "toybox", "--org", "personal").stdout
    assert "# Decision log: personal/toybox" in toy and "Other project decision" in toy and "Pin images" not in toy

    whole_org = arcane.cli("decisions", "--org", "Acme").stdout
    assert "# Decision log: acme\n" in whole_org and "Plain decision (`" in whole_org and "· widget" in whole_org

    empty = arcane.cli("decisions", "--project", "nothing-here").stdout
    assert "No current decisions." in empty and "Nothing replaced." in empty
