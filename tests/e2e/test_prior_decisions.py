"""E2E: saving a decision shows earlier decisions on the same files, with the options they weighed.

The real ``arcane mcp`` server and ``arcane save`` CLI run against a temp store.
"""

from __future__ import annotations

import re
from typing import Any

from tests.e2e.conftest import Arcane, Client

FILE = "src/zephyr/quux_handler.py"
OPTIONS = (
    "## Context\nWhy now.\n\n## Options considered\n- Redis cache: too heavy\n- In-process dict: chosen\n\n"
    "## Decision\nDict."
)


async def _decision(c: Client, title: str, files: list[str], details: str | None = None, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"related_files": files, **kw}
    if details:
        args["details"] = details
    return await c.call(
        "memory_save",
        title=title,
        what=f"{title} what",
        why="Because the reasons are long enough here",
        category="decision",
        **args,
    )


def test_overlapping_decisions_come_back_with_options_and_shared_files(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        first = await _decision(c, "Cache handler results", [FILE, "docs/a.md"], OPTIONS)
        await _decision(c, "Unrelated", ["other/file.py"], OPTIONS)
        # Same file name in another directory is a candidate but not the same file.
        await _decision(c, "Same name elsewhere", ["lib/quux_handler.py"], OPTIONS)
        await c.call("memory_save", title="A bug", what="w", category="bug", related_files=[FILE])
        # An absolute path from another checkout still names the same file.
        absolute = await _decision(c, "Old absolute path", [f"/Users/x/repo/{FILE}"])
        new = await _decision(c, "Tune handler cache", [FILE])
        return {"first": first, "absolute": absolute, "new": new}

    out = arcane.run(scenario)
    assert "prior_decisions" not in out["first"]
    prior = {p["title"]: p for p in out["new"]["prior_decisions"]}
    assert set(prior) == {"Cache handler results", "Old absolute path"}
    entry = prior["Cache handler results"]
    assert entry["shared_files"] == [FILE]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"])
    assert entry["options"].startswith("- Redis cache: too heavy")
    assert "Decision" not in entry["options"] and "Why now" not in entry["options"]
    assert "options" not in prior["Old absolute path"]
    assert prior["Old absolute path"]["shared_files"] == [f"/Users/x/repo/{FILE}"]
    assert out["absolute"]["prior_decisions"][0]["title"] == "Cache handler results"


def test_superseded_listed_apart_and_the_one_being_replaced_left_out(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        old = await _decision(c, "Old way", [FILE], "Options considered: A, B\nDecision: A")
        mid = await _decision(c, "Middle way", [FILE], "Alternatives:\nx then y\n\nTradeoffs: none")
        replacement = await _decision(c, "Replacement", [FILE], supersedes=old["id"])
        new = await _decision(c, "Newest", [FILE], supersedes=mid["id"])
        return {"old": old, "new": new, "replacement": replacement}

    out = arcane.run(scenario)
    prior = out["new"]["prior_decisions"]
    by_title = {p["title"]: p for p in prior}
    assert [p["title"] for p in prior if "superseded_by" not in p] == ["Replacement"]
    # "Middle way" is what "Newest" replaces, so it is not a prior decision to it; the older "Old way" still is.
    assert set(by_title) == {"Replacement", "Old way"}
    assert by_title["Old way"]["id"] == out["old"]["id"]
    assert by_title["Old way"]["superseded_by"] == out["replacement"]["id"]
    assert by_title["Old way"]["options"] == "A, B"
    assert "Middle way" not in by_title


def test_caps_and_excerpt_length(arcane: Arcane) -> None:
    long = "## Rejected\n" + "word " * 200 + "\n\n## Decision\nx"

    async def scenario(c: Client) -> dict[str, Any]:
        olds = [await _decision(c, f"Cur {n}", [FILE], long) for n in range(12)]
        for n, old in enumerate(olds[:4]):
            await _decision(c, f"Repl {n}", ["elsewhere.py"], supersedes=old["id"])
        return await _decision(c, "Newest", [FILE])

    prior = arcane.run(scenario)["prior_decisions"]
    # Current ones newest first, then replaced ones newest first.
    assert [p["title"] for p in prior] == ["Cur 11", "Cur 10", "Cur 9", "Cur 8", "Cur 7", "Cur 3", "Cur 2", "Cur 1"]
    assert all("superseded_by" in p for p in prior[5:])
    assert all(len(p["options"]) <= 300 for p in prior)


def test_not_run_for_other_categories_or_no_files_and_merged_saves_get_it(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await _decision(c, "Earlier", [FILE])
        learning = await c.call("memory_save", title="L", what="w", category="learning", related_files=[FILE])
        nofiles = await _decision(c, "No files", [])
        first = await _decision(c, "Same title", [FILE])
        merged = await _decision(c, "Same title", [FILE])
        return {"learning": learning, "nofiles": nofiles, "merged": merged, "first": first}

    out = arcane.run(scenario)
    assert "prior_decisions" not in out["learning"] and "prior_decisions" not in out["nofiles"]
    assert out["merged"]["action"] == "updated"
    assert [p["title"] for p in out["merged"]["prior_decisions"]] == ["Earlier"]


def test_cli_save_prints_prior_decisions(arcane: Arcane) -> None:
    first = arcane.cli(
        "save",
        "--title",
        "First",
        "--what",
        "w",
        "--category",
        "decision",
        "--related-files",
        FILE,
        "--details",
        "Options considered: A, B",
    )
    first_id = re.search(r"\(id: ([0-9a-f-]+)\)", first.stdout).group(1)  # type: ignore[union-attr]
    base = ("save", "--what", "w", "--category", "decision", "--related-files", FILE)
    arcane.cli(*base, "--title", "Second", "--supersedes", first_id)
    out = arcane.cli(*base, "--title", "Third")
    assert "Prior decisions on these files:" in out.stdout
    assert "Second" in out.stdout and "First (superseded)" in out.stdout and "Options: A, B" in out.stdout


def test_options_excerpt_reads_name_reason_lists_and_ignores_prose(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await _decision(c, "Listed", [FILE], "Options considered:\nRedis: too heavy\nDict: chosen\n\nDecision: dict")
        await _decision(c, "Prose options", [FILE], "Options were limited because of the deadline.")
        await _decision(c, "Prose rejected", [FILE], "Rejected the Redis idea since ops refused.")
        return await _decision(c, "Newest", [FILE])

    by_title = {p["title"]: p for p in arcane.run(scenario)["prior_decisions"]}
    assert by_title["Listed"]["options"] == "Redis: too heavy Dict: chosen"
    assert "options" not in by_title["Prose options"] and "options" not in by_title["Prose rejected"]


def test_options_excerpt_stops_at_the_next_section_or_paragraph(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await _decision(c, "Bold", [FILE], "**Options considered:** A, B\n**Decision:** A")
        await _decision(c, "Paragraph after", [FILE], "Options: A, B\n\nWe chose A since it is fast.")
        await _decision(c, "Qualified", [FILE], "Context: x\n\nOptions considered for the cache:\n1. A\n2. B")
        await _decision(c, "Bare", [FILE], "Options considered\n- A\n- B\n\nDecision: A")
        return await _decision(c, "Newest", [FILE])

    async def headings(c: Client) -> dict[str, Any]:
        await _decision(c, "Alternatives heading", [FILE], "## Alternatives considered\n- A\n- B")
        await _decision(c, "Counted heading", [FILE], "## Options Considered (3)\n- A")
        await _decision(c, "Titled heading", [FILE], "### Rejected approach\nfoo")
        return await _decision(c, "Newest after headings", [FILE])

    by_title = {p["title"]: p for p in arcane.run(scenario)["prior_decisions"]}
    assert by_title["Bold"]["options"] == "A, B"
    assert by_title["Paragraph after"]["options"] == "A, B"
    assert by_title["Qualified"]["options"] == "1. A 2. B"
    assert by_title["Bare"]["options"] == "- A - B"
    by_title = {p["title"]: p for p in arcane.run(headings)["prior_decisions"]}
    assert by_title["Alternatives heading"]["options"] == "- A - B"
    assert by_title["Counted heading"]["options"] == "- A"
    assert by_title["Titled heading"]["options"] == "foo"


def test_options_excerpt_joins_the_rejected_part_after_the_options(arcane: Arcane) -> None:
    async def scenario(c: Client) -> dict[str, Any]:
        await _decision(c, "Split", [FILE], "Options:\n- A\nRejected: B because slow\n\nWe chose A.")
        return await _decision(c, "Newest", [FILE])

    [prior] = arcane.run(scenario)["prior_decisions"]
    assert prior["options"] == "- A Rejected: B because slow"
