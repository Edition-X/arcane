"""E2E: ``arcane decisions`` over a store filled through the MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.e2e.conftest import Arcane, Client, git

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
    assert 1100 <= len(long_section) <= 1201 and long_section.endswith("…")


def test_output_is_deterministic_and_written_only_with_out(arcane: Arcane, tmp_path: Path) -> None:
    _fill(arcane)
    first = arcane.cli("decisions").stdout
    assert arcane.cli("decisions").stdout == first
    assert git(arcane.repo, "status", "--porcelain") == ""  # nothing written without --out

    target = tmp_path / "log.md"
    message = arcane.cli("decisions", "--out", str(target)).stdout
    assert "Wrote 3 decisions and 1 replaced" in message
    assert target.read_text(encoding="utf-8") == first

    failed = arcane.cli("decisions", "--out", str(tmp_path / "missing" / "log.md"), check=False)
    assert failed.returncode == 1 and "Traceback" not in failed.stderr
    assert "Cannot write" in failed.stderr and "No such file or directory" in failed.stderr


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


def test_project_alone_finds_a_project_in_another_org(arcane: Arcane) -> None:
    ids = _fill(arcane)  # run from the acme/widget repo; toybox lives in org personal

    out = arcane.cli("decisions", "--project", "toybox").stdout
    assert out.startswith("# Decision log: toybox (all orgs)\n\n1 current · 0 replaced\n")
    assert f"Other project decision (`{ids['other'][:8]}`)" in out

    with (arcane.home / "config.yaml").open("a", encoding="utf-8") as handle:
        handle.write("orgs:\n  overrides:\n    toybox: personal\n")
    pinned = arcane.cli("decisions", "--project", "toybox").stdout
    assert pinned.startswith("# Decision log: personal/toybox\n\n1 current")


def test_bullet_lines_stay_inside_their_section(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await c.call(
            "memory_save", title="Bulleted trade-offs", what="Pick one", why="Because", category="decision",
            details="Tradeoffs:\n- Pros: lower blast radius\n- Cons: adds a temporary playbook\n\nFollow-up: later",
        )  # fmt: skip
        await c.call(
            "memory_save", title="Bulleted options", what="Pick one", why="Because", category="decision",
            details="Options considered:\n- Option A: keep tags\n1. Option B: pin digests\n* Option C: vendor it",
        )  # fmt: skip

    arcane.run(scenario)
    out = arcane.cli("decisions").stdout

    assert "**Tradeoffs**\n\n> - Pros: lower blast radius\n> - Cons: adds a temporary playbook\n" in out
    assert "**Pros**" not in out and "**Cons**" not in out and "Follow-up" not in out
    assert (
        "**Options considered**\n\n> - Option A: keep tags\n> 1. Option B: pin digests\n> * Option C: vendor it\n"
        in out
    )
    assert "**Option A**" not in out


def _save_decisions(arcane: Arcane, details_by_title: dict[str, str]) -> None:
    async def scenario(c: Client) -> None:
        for title, details in details_by_title.items():
            await c.call(
                "memory_save", title=title, what="Pick one", why="Because", category="decision", details=details
            )

    arcane.run(scenario)


def _options(arcane: Arcane) -> dict[str, list[dict[str, str]]]:
    data = json.loads(arcane.cli("decisions", "--format", "json").stdout)
    return {d["title"]: d["options"] for d in data["decisions"]}


def test_every_heading_form_and_name_reason_lines_are_kept_whole(arcane: Arcane) -> None:
    _save_decisions(
        arcane,
        {
            "Bold colon inside": "**Options considered:**\n- A\n- B\n**Decision:** A",
            "Bold colon outside": "**Options considered**:\n- A\n- B",
            "Name reason lines": "Options:\nTags: simple but they move\nDigests: exact\n\nDecision: digests",
            "Lowercase": "options considered:\n- tags\n- digests",
            "Prose": "Options were limited because of the deadline.",
        },
    )
    options = _options(arcane)

    assert options["Bold colon inside"] == [{"label": "Options considered", "text": "- A\n- B"}]
    assert options["Bold colon outside"] == [{"label": "Options considered", "text": "- A\n- B"}]
    assert options["Name reason lines"] == [{"label": "Options", "text": "Tags: simple but they move\nDigests: exact"}]
    assert options["Lowercase"] == [{"label": "options considered", "text": "- tags\n- digests"}]
    assert options["Prose"] == []


def test_a_code_fence_inside_options_stays_in_one_blockquote(arcane: Arcane) -> None:
    _save_decisions(
        arcane,
        {
            "Fenced": "Options:\n```bash\n# install the thing\nmake all\n```\n- Redis\n\nDecision: dict",
            "Fence cut short": "Options:\n```\n" + "word " * 600 + "\n```",
        },
    )
    out = arcane.cli("decisions").stdout

    assert "**Options**\n\n> ```bash\n> # install the thing\n> make all\n> ```\n> - Redis\n\n" in out
    assert "Decision: dict" not in out
    cut = out.split("**Options**\n\n> ```\n", 1)[1].split("\n\n", 1)[0]
    assert cut.endswith("…\n> ```")  # the cap closes the fence it cut, so the rest of the log renders normally


def test_json_and_markdown_carry_the_same_what_why_and_options(arcane: Arcane) -> None:
    ids = _fill(arcane)
    data = json.loads(arcane.cli("decisions", "--format", "json").stdout)
    entry = next(d for d in data["decisions"] if d["id"] == ids["new"])
    out = arcane.cli("decisions").stdout

    assert f"**What:** {entry['what']}\n\n**Why:** {entry['why']}\n" in out
    assert [o["label"] for o in entry["options"]] == ["Options considered", "Trade-offs"]
    for option in entry["options"]:
        quoted = "\n".join(f"> {line}".rstrip() for line in option["text"].splitlines())
        assert f"**{option['label']}**\n\n{quoted}\n" in out


def test_memoryignore_redacts_values_never_json_keys_or_labels(arcane: Arcane) -> None:
    _save_decisions(arcane, {"Cache choice": "Options considered:\n- the title wins\n- a rank"})
    (arcane.home / ".memoryignore").write_text("title\nWhat\n", encoding="utf-8")

    data = json.loads(arcane.cli("decisions", "--format", "json").stdout)
    [entry] = data["decisions"]
    assert set(entry) == {"id", "date", "title", "project", "what", "why", "options"}
    assert entry["options"][0]["text"] == "- the [REDACTED] wins\n- a rank"

    out = arcane.cli("decisions").stdout
    assert "**What:** Pick one" in out and "[REDACTED]" in out


def test_prose_after_an_options_list_stays_out_and_fences_close_with_their_own_marker(arcane: Arcane) -> None:
    _save_decisions(
        arcane,
        {
            "Prose after": "Options:\n- A\n- B\n\nWe went with A after a long chat.\n\nMore narrative.",
            "Gapped list": "Options:\n- A\n\n- B\n\n  indented note\n\nRisks: none",
            "Tilde fence": "Options:\n~~~\n" + "word " * 600 + "\n~~~",
            "Open fence": "Options:\n- A\n```bash\nmake all",
        },
    )
    options = _options(arcane)

    assert options["Prose after"] == [{"label": "Options", "text": "- A\n- B"}]
    assert options["Gapped list"] == [{"label": "Options", "text": "- A\n\n- B\n\n  indented note"}]
    [tilde] = options["Tilde fence"]
    assert tilde["text"].startswith("~~~\n") and tilde["text"].endswith("…\n~~~")
    assert options["Open fence"] == [{"label": "Options", "text": "- A\n```bash\nmake all\n```"}]
