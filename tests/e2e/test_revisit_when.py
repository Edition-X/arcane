"""E2E: a memory with a revisit_when date comes back in memory_context once the date has come."""

from __future__ import annotations

import subprocess
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client, FakeOllama

TODAY = {"ARCANE_TODAY": "2026-06-15"}


def _save(c: Client, title: str, **extra: Any) -> Any:
    return c.call("memory_save", title=title, what=f"What {title}", category="context", **extra)


def test_bad_dates_are_rejected_everywhere(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        saved = await _save(c, "Keeper")
        for bad in ("2026-02-30", "tomorrow", "2026-6-1", "20260601", "2026-06-01T10:00"):
            # The schema rejects a wrong shape; the handler rejects a shape-correct date that does not exist.
            for error in (
                await c.error("memory_save", title=f"Bad {bad}", what="w", revisit_when=bad),
                await c.error("memory_update", memory_id=saved["id"], revisit_when=bad),
            ):
                assert "revisit_when" in error or bad in error

    arcane.run(scenario)
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(1,)]
    failed = arcane.cli("save", "--title", "Bad", "--what", "w", "--revisit-when", "2026-02-30", check=False)
    assert failed.returncode != 0
    assert "2026-02-30" in failed.stderr
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(1,)]


def test_date_round_trips_through_save_update_details_and_search(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        saved = await _save(c, "Pinned library choice", revisit_when="2026-09-01")
        record = await c.call("memory_details", memory_id=saved["id"])
        assert record["revisit_when"] == "2026-09-01"
        hit = (await c.call("memory_search", query="pinned library"))[0]
        assert hit["revisit_when"] == "2026-09-01"
        full = (await c.call("memory_search", query="pinned library", detail="full"))[0]
        assert full["revisit_when"] == "2026-09-01"

        await c.call("memory_update", memory_id=saved["id"], revisit_when="2026-10-02")
        assert (await c.call("memory_details", memory_id=saved["id"]))["revisit_when"] == "2026-10-02"

        await c.call("memory_update", memory_id=saved["id"], revisit_when="")
        assert "revisit_when" not in await c.call("memory_details", memory_id=saved["id"])
        assert "revisit_when" not in (await c.call("memory_search", query="pinned library"))[0]

        plain = await _save(c, "No date at all")
        assert "revisit_when" not in await c.call("memory_details", memory_id=plain["id"])

    arcane.run(scenario)
    assert arcane.sql("SELECT revisit_when FROM memories WHERE title = 'Pinned library choice'") == [(None,)]


def test_same_title_save_sets_the_date_and_keeps_it_when_omitted(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        first = await _save(c, "Merged twice")
        again = await _save(c, "Merged twice", revisit_when="2026-07-07")
        assert again["id"] == first["id"]
        await _save(c, "Merged twice")
        assert (await c.call("memory_details", memory_id=first["id"]))["revisit_when"] == "2026-07-07"

    arcane.run(scenario)


def test_context_lists_due_memories_oldest_first_capped_and_whatever_the_query(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        ids = {}
        for n in range(1, 8):  # seven due memories; only the five oldest dates come back
            saved = await _save(c, f"Due {n}", revisit_when=f"2026-05-0{9 - n}")
            ids[n] = saved["id"]
        await _save(c, "Due today", revisit_when="2026-06-15")
        await _save(c, "Not yet", revisit_when="2026-06-16")
        await _save(c, "No date")

        context = await c.call("memory_context")
        assert list(context)[0] == "revisit"
        block = context["revisit"]
        assert [r["revisit_when"] for r in block] == [
            "2026-05-02",
            "2026-05-03",
            "2026-05-04",
            "2026-05-05",
            "2026-05-06",
        ]
        assert [r["id"] for r in block] == [ids[7], ids[6], ids[5], ids[4], ids[3]]
        assert set(block[0]) == {"id", "title", "category", "revisit_when", "project"}
        assert block[0]["project"] == "widget"
        assert block[0]["category"] == "context"

        for kwargs in ({"query": "zzzz nothing matches"}, {"query": "Not yet"}, {"detail": "minimal"}):
            assert len((await c.call("memory_context", **kwargs))["revisit"]) == 5

    arcane.run(scenario, extra_env=TODAY)


def test_nothing_due_adds_no_block(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await _save(c, "Later", revisit_when="2026-06-16")
        await _save(c, "Undated")
        assert "revisit" not in await c.call("memory_context")

    arcane.run(scenario, extra_env=TODAY)


def test_replaced_expired_and_out_of_scope_memories_are_left_out(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        old = await _save(c, "Old plan", revisit_when="2026-01-01")
        await _save(c, "New plan", supersedes=old["id"])
        stale = await _save(c, "Lapsed note", revisit_when="2026-01-02", ttl_days=1)
        await _save(c, "Other org note", revisit_when="2026-01-03", org="rival", project="elsewhere")
        await _save(c, "Live note", revisit_when="2026-01-04")
        arcane.sql("UPDATE memories SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (stale["id"],))

        block = (await c.call("memory_context"))["revisit"]
        assert [r["title"] for r in block] == ["Live note"]

        # The date stays on the old memory: replacing it hides it, it does not clear it.
        assert (await c.call("memory_details", memory_id=old["id"]))["revisit_when"] == "2026-01-01"

    arcane.run(scenario, extra_env=TODAY)


def test_org_level_and_sibling_project_memories_are_due_when_the_context_reads_them(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await _save(c, "Org rule", revisit_when="2026-02-01", scope="org")
        await _save(c, "Sibling project", revisit_when="2026-02-02", project="gadget")
        block = (await c.call("memory_context"))["revisit"]
        assert [(r["title"], r["project"]) for r in block] == [("Org rule", ""), ("Sibling project", "gadget")]
        narrow = await c.call("memory_context", scope="project")
        assert "revisit" not in narrow

    arcane.run(scenario, extra_env=TODAY)


def test_context_cli_prints_the_same_block(arcane: Arcane) -> None:
    arcane.cli(
        "save", "--title", "Check the pin", "--what", "w", "--revisit-when", "2026-06-01", "--category", "decision"
    )
    arcane.cli("save", "--title", "Later one", "--what", "w", "--revisit-when", "2026-07-01")

    def context(today: str) -> str:
        env = {**arcane.env("full"), "ARCANE_TODAY": today}
        return subprocess.run(
            [ARCANE, "context", "--project"], cwd=arcane.repo, env=env, capture_output=True, text=True, check=True
        ).stdout

    due = context("2026-06-15")
    assert due.startswith("Due for a second look (1):\n- [2026-06-01] Check the pin (widget) [decision] (id: ")
    assert "Later one" not in due.split("Available memories")[0]
    assert "Available memories" in due
    assert "Due for a second look" not in context("2026-05-31")

    shown = arcane.cli("details", arcane.sql("SELECT id FROM memories WHERE title = 'Check the pin'")[0][0]).stdout
    assert "Revisit: 2026-06-01" in shown


def test_a_bad_today_override_is_an_error_not_a_traceback_or_a_silent_fallback(arcane: Arcane) -> None:
    arcane.cli("save", "--title", "Some memory", "--what", "w")
    env = {**arcane.env("full"), "ARCANE_TODAY": "next week"}
    run = subprocess.run([ARCANE, "context"], cwd=arcane.repo, env=env, capture_output=True, text=True)
    assert run.returncode != 0
    assert "ARCANE_TODAY" in run.stderr
    assert "Traceback" not in run.stderr

    async def scenario(c: Client) -> None:
        assert "ARCANE_TODAY" in await c.error("memory_context")

    arcane.run(scenario, extra_env={"ARCANE_TODAY": "next week"})


def test_a_store_from_before_the_column_is_migrated_on_open(arcane: Arcane) -> None:
    arcane.cli("save", "--title", "Written before", "--what", "w")
    arcane.sql("ALTER TABLE memories DROP COLUMN revisit_when")
    assert "revisit_when" not in [row[1] for row in arcane.sql("PRAGMA table_info(memories)")]

    async def scenario(c: Client) -> None:
        saved = await _save(c, "Written after", revisit_when="2026-01-01")
        assert (await c.call("memory_context"))["revisit"][0]["id"] == saved["id"]

    arcane.run(scenario, extra_env=TODAY)
    assert "revisit_when" in [row[1] for row in arcane.sql("PRAGMA table_info(memories)")]
    assert arcane.sql("SELECT revisit_when FROM memories WHERE title = 'Written before'") == [(None,)]


def test_the_block_does_not_change_with_the_query(arcane: Arcane) -> None:
    """A query that matches nothing makes context widen to the org; the due list must not follow it."""

    async def scenario(c: Client) -> None:
        for n in range(3):  # three own memories: the project can answer without the org
            await _save(c, f"Own memory {n}")
        await _save(c, "Sibling due", revisit_when="2026-02-02", project="gadget")
        assert "revisit" not in await c.call("memory_context")
        assert "revisit" not in await c.call("memory_context", query="zzzz nothing matches")
        assert "revisit" not in await c.call("memory_context", query="Own memory")

    arcane.run(scenario, extra_env=TODAY)

    env = {**arcane.env("full"), "ARCANE_TODAY": TODAY["ARCANE_TODAY"]}
    for args in (["--project"], ["--project", "--query", "zzzz nothing matches"]):
        out = subprocess.run([ARCANE, "context", *args], cwd=arcane.repo, env=env, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "Due for a second look" not in out.stdout


def test_a_thin_project_lists_the_sibling_whatever_the_query(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await _save(c, "Only own memory")
        await _save(c, "Sibling due", revisit_when="2026-02-02", project="gadget")
        for kwargs in ({}, {"query": "zzzz nothing matches"}, {"query": "Only own memory"}):
            assert [r["title"] for r in (await c.call("memory_context", **kwargs))["revisit"]] == ["Sibling due"]

    arcane.run(scenario, extra_env=TODAY)


def test_a_memory_due_today_is_listed_and_one_due_tomorrow_is_not(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        await _save(c, "Due today", revisit_when="2026-06-15")
        await _save(c, "Due tomorrow", revisit_when="2026-06-16")
        assert [r["title"] for r in (await c.call("memory_context"))["revisit"]] == ["Due today"]

    arcane.run(scenario, extra_env=TODAY)


def test_changing_only_the_date_does_not_embed_again(arcane: Arcane, ollama: FakeOllama) -> None:
    async def scenario(c: Client) -> None:
        saved = await _save(c, "Embedded once")
        ollama.prompts.clear()
        await c.call("memory_update", memory_id=saved["id"], revisit_when="2026-09-01")
        await c.call("memory_update", memory_id=saved["id"], revisit_when="")
        assert ollama.prompts == []
        await c.call("memory_update", memory_id=saved["id"], what="Changed text")
        assert len(ollama.prompts) == 1

    arcane.run(scenario)
