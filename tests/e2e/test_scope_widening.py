"""Search and context read past the current project when it is thin, on request, or never.

The server runs in a repo whose remote is ``Acme/widget``, so scope resolves to
org ``acme``, project ``widget``.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from tests.e2e.conftest import ARCANE, Arcane, Client

DETAIL_LEVELS = ("minimal", "standard", "full")


async def _save(client: Client, title: str, what: str, project: str, org: str = "acme") -> None:
    await client.call("memory_save", title=title, what=what, why="because", project=project, org=org)


def _cli(arcane: Arcane, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True, check=check
    )


def test_thin_project_search_reads_sibling_projects_and_labels_hits(arcane: Arcane) -> None:
    async def scenario(client: Client) -> None:
        await _save(client, "Kafka retry policy", "kafka retry backs off twice", "gadget")
        await _save(client, "Beta kafka retry", "kafka retry in another org", "gizmo", org="beta")

        for detail in DETAIL_LEVELS:
            hits = await client.call("memory_search", query="kafka retry", detail=detail)
            assert [h["title"] for h in hits] == ["Kafka retry policy"], detail
            # Provenance is on every hit at every detail level, so a sibling's hit is told from a local one.
            assert (hits[0]["project"], hits[0]["org"], hits[0]["scope_match"]) == ("gadget", "acme", "other_project")

    arcane.run(scenario)


def test_local_hit_ranks_first_on_equal_relevance_and_strong_sibling_beats_weak_local(arcane: Arcane) -> None:
    async def scenario(client: Client) -> None:
        await _save(client, "Cache eviction rule", "cache eviction uses lru", "gadget")
        await _save(client, "Cache eviction note", "cache eviction uses lru", "widget")
        hits = await client.call("memory_search", query="cache eviction lru")
        assert [(h["project"], h["scope_match"]) for h in hits] == [("widget", "project"), ("gadget", "other_project")]

        # One weak local match leaves the project thin; the sibling's exact match must still win.
        await _save(client, "Deploy checklist", "deploy checklist lists database backups", "widget")
        await _save(client, "Deploy database backups", "deploy database backups nightly", "gadget")
        await _save(client, "Deploy", "deploy", "widget")
        hits = await client.call("memory_search", query="deploy database backups nightly", limit=2)
        assert hits[0]["project"] == "gadget"

    arcane.run(scenario)


def test_populated_project_does_not_widen_and_automatic_widening_stays_in_the_org(arcane: Arcane) -> None:
    async def scenario(client: Client) -> None:
        for n in ("one", "two", "three"):
            await _save(client, f"Queue tuning {n}", "queue tuning raises workers", "widget")
        await _save(client, "Queue tuning sibling", "queue tuning in the sibling", "gadget")
        hits = await client.call("memory_search", query="queue tuning")
        assert {h["project"] for h in hits} == {"widget"}

        await _save(client, "Ledger rounding", "ledger rounding is bankers", "ledger", org="beta")
        assert await client.call("memory_search", query="ledger rounding") == {
            "results": [],
            "message": (
                "No match in this project or its org. Retry with scope='all' to search every project in every org."
            ),
        }
        everywhere = await client.call("memory_search", query="ledger rounding", scope="all")
        assert [(h["org"], h["scope_match"]) for h in everywhere] == [("beta", "other_org")]

        # An empty `all` search has nowhere wider to point, so it stays a plain list.
        assert await client.call("memory_search", query="zebra unicorn", scope="all") == []

    arcane.run(scenario)


def test_explicit_scope_never_widens_and_unknown_scope_is_an_error(arcane: Arcane) -> None:
    async def scenario(client: Client) -> None:
        await _save(client, "Kafka retry policy", "kafka retry backs off twice", "gadget")
        await _save(client, "Org wide rule", "kafka rule for the whole org", "")
        for scope in ("project", "global"):
            hits = await client.call("memory_search", query="kafka", scope=scope)
            assert hits["results"] == [], scope
        org_hits = await client.call("memory_search", query="kafka", scope="org")
        assert [h["title"] for h in org_hits] == ["Org wide rule"]
        assert "'nearby' is not one of" in await client.error("memory_search", query="kafka", scope="nearby")

    arcane.run(scenario)


def test_context_widens_for_a_thin_project_and_says_so(arcane: Arcane) -> None:
    async def scenario(client: Client) -> None:
        await _save(client, "Gadget decision", "gadget picked sqlite", "gadget")

        for query in (None, "gadget sqlite"):
            args = {"query": query} if query else {}
            payload = await client.call("memory_context", **args)
            assert payload["scope"]["widened"] is True and payload["scope"]["reach"] == "org"
            assert [(m["title"], m["project"], m["scope_match"]) for m in payload["memories"]] == [
                ("Gadget decision", "gadget", "other_project")
            ], query

        narrow = await client.call("memory_context", scope="project")
        assert narrow["memories"] == [] and narrow["scope"]["widened"] is False

        for n in ("one", "two", "three"):
            await _save(client, f"Widget note {n}", "widget keeps notes", "widget")
        full = await client.call("memory_context")
        assert full["scope"]["widened"] is False
        assert {m["project"] for m in full["memories"]} == {"widget"}

        await _save(client, "Other org memory", "beta keeps notes", "gizmo", org="beta")
        everything = await client.call("memory_context", scope="all", limit=20)
        assert "Other org memory" in {m["title"] for m in everything["memories"]}

    arcane.run(scenario)


def test_explicit_org_is_lowercased_on_search_and_context(arcane: Arcane) -> None:
    # An explicit "Sunrise-Robotics" was compared to stored lowercase slugs and matched nothing.
    async def scenario(client: Client) -> None:
        await _save(client, "Gadget decision", "gadget picked sqlite", "gadget")
        hits = await client.call("memory_search", query="gadget sqlite", org="ACME", project="gadget")
        assert [h["title"] for h in hits] == ["Gadget decision"]
        payload = await client.call("memory_context", org="ACME", project="gadget")
        assert payload["scope"]["org"] == "acme"
        assert [m["title"] for m in payload["memories"]] == ["Gadget decision"]

    arcane.run(scenario)


def test_cli_search_scope_all_and_hint(arcane: Arcane) -> None:
    async def seed(client: Client) -> None:
        await _save(client, "Ledger rounding", "ledger rounding is bankers", "ledger", org="beta")

    arcane.run(seed)
    scoped = _cli(arcane, "search", "ledger rounding", "--project").stdout
    assert "No results found." in scoped and "--scope all" in scoped
    everywhere = _cli(arcane, "search", "ledger rounding", "--scope", "all").stdout
    assert "Ledger rounding" in everywhere and "beta" in everywhere


def test_merge_projects_moves_journeys_artifacts_insights_and_backs_up_first(arcane: Arcane) -> None:
    async def seed(client: Client) -> None:
        await _save(client, "Old name note", "kept under the old name", "old-name")
        await client.call("journey_start", title="Old name journey", project="old-name")

    arcane.run(seed)
    now = "2026-01-01T00:00:00+00:00"
    for org in ("acme", "beta"):
        arcane.sql(
            "INSERT INTO artifacts (id, artifact_type, external_id, title, project, org, created_at) "
            "VALUES (?, 'commit', ?, 'a commit', 'old-name', ?, ?)",
            (str(uuid.uuid4()), "abc123", org, now),
        )
        arcane.sql(
            "INSERT INTO insights (id, insight_type, title, body, project, org, created_at) "
            "VALUES (?, 'velocity', 'an insight', 'body', 'old-name', ?, ?)",
            (str(uuid.uuid4()), org, now),
        )

    def where(table: str) -> list[tuple[str, str]]:
        return [(org, project) for org, project in arcane.sql(f"SELECT org, project FROM {table} ORDER BY org")]  # noqa: S608

    dry = _cli(arcane, "merge-projects", "old-name", "new-name", "--org", "ACME").stdout
    assert "would move 1 memories, 1 journeys, 1 artifacts, 1 insights from 'old-name' in org acme" in dry
    assert not (Path(arcane.home) / "backups").exists()
    assert where("journeys") == [("acme", "old-name")]

    applied = _cli(arcane, "merge-projects", "old-name", "new-name", "--org", "acme", "--apply").stdout
    assert "Moved 1 memories, 1 journeys, 1 artifacts, 1 insights from 'old-name' in org acme" in applied
    assert len(list((Path(arcane.home) / "backups").glob("*.tar.gz"))) == 1
    assert where("journeys") == [("acme", "new-name")]
    # beta's rows share the old name and stay put.
    assert where("artifacts") == [("acme", "new-name"), ("beta", "old-name")]
    assert where("insights") == [("acme", "new-name"), ("beta", "old-name")]
