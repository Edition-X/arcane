"""E2E: what the CLI shows a user, driven through the installed `arcane` command."""

from __future__ import annotations

import subprocess

from tests.e2e.conftest import ARCANE, Arcane, Client


def _cli(arcane: Arcane, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True, check=check
    )


def test_builtin_plugins_list_once_under_their_command_names(arcane: Arcane) -> None:
    # `gha` runs the `github_actions` entry point; listing both offered a
    # second, undocumented command for the same plugin.
    commands = _cli(arcane, "ingest", "--help").stdout.split("Commands:", 1)[1].split()
    assert "gha" in commands and "github_actions" not in commands
    for group, names in (
        ("ingest", ("git", "gha", "linear")),
        ("analyze", ("velocity", "health", "usage")),
        ("draft", ("blog", "adr")),
    ):
        listed = dict(line.split(": ", 1) for line in _cli(arcane, group, "--list").stdout.splitlines())
        assert set(names) <= set(listed), listed
        assert "(no description)" not in listed.values()


def test_provider_none_is_keyword_search_without_warnings(arcane: Arcane) -> None:
    (arcane.home / "config.yaml").write_text("embedding:\n  provider: none\n", encoding="utf-8")
    saved = _cli(arcane, "save", "--title", "Keyword only", "--what", "Stored without a vector")
    assert "Embedding failed" not in saved.stderr and "Unknown embedding provider" not in saved.stderr
    _cli(arcane, "save", "--title", "Categorised", "--what", "Stored without a vector", "--category", "bug")

    found = _cli(arcane, "search", "vector").stdout
    assert "Keyword only" in found and "Categorised" in found
    # A memory with no category prints no placeholder for it.
    assert "None |" not in found
    assert "     bug | " in found
    assert arcane.sql("SELECT count(*) FROM memories") == [(2,)]

    reindex = _cli(arcane, "reindex", check=False)
    assert reindex.returncode == 1
    assert "Embeddings are disabled (embedding.provider: none)" in reindex.stderr


def test_unusable_id_prefixes_are_reported_not_raised(arcane: Arcane) -> None:
    # The MCP handlers already turned these into errors; the CLI printed a
    # traceback for every command that takes an ID.
    for args in (
        ("details", "abc"),
        ("delete", "abc"),
        ("journey", "show", "abc"),
        ("journey", "update", "abc", "--summary", "x"),
        ("journey", "complete", "abc"),
    ):
        result = _cli(arcane, *args, check=False)
        assert result.returncode == 1, args
        assert "Traceback" not in result.stderr, args
        assert "ID prefix must be at least 8 characters" in result.stderr, args


def test_merge_projects_moves_one_orgs_memories_only(arcane: Arcane) -> None:
    # reassign_project once had no org filter, so merging alpha's "widget" also
    # moved beta's "widget" — two unrelated orgs merged by a name collision.

    async def seed(client: Client) -> None:
        for org in ("alpha", "beta"):
            await client.call("memory_save", title=f"{org} note", what="shared name", project="widget", org=org)

    arcane.run(seed)

    def orgs_in(project: str) -> list[str]:
        return [row[0] for row in arcane.sql("SELECT org FROM memories WHERE project = ? ORDER BY org", (project,))]

    ambiguous = _cli(arcane, "merge-projects", "widget", "gadget", "--apply", check=False)
    assert ambiguous.returncode == 2
    assert "exists in several orgs: alpha (1), beta (1)" in ambiguous.stderr
    assert orgs_in("widget") == ["alpha", "beta"]

    dry_run = _cli(arcane, "merge-projects", "widget", "gadget", "--org", "alpha").stdout
    assert "would move 1 memories from 'widget' in org alpha" in dry_run
    assert orgs_in("widget") == ["alpha", "beta"]

    applied = _cli(arcane, "merge-projects", "widget", "gadget", "--org", "alpha", "--apply").stdout
    assert "Moved 1 memories from 'widget' in org alpha into 'gadget'" in applied
    assert orgs_in("widget") == ["beta"]
    assert orgs_in("gadget") == ["alpha"]


def test_health_advice_for_orgless_memories_actually_repairs_them(arcane: Arcane) -> None:
    # The insight used to recommend `merge-projects '' <project>`, which left
    # org empty (still invisible) and would also sweep in every org-level memory.
    _cli(arcane, "save", "--title", "Legacy", "--what", "predates orgs")
    arcane.sql("UPDATE memories SET org = '', project = '' WHERE title = 'Legacy'")

    _cli(arcane, "analyze", "health")
    [(body,)] = arcane.sql("SELECT body FROM insights WHERE insight_type = 'health_empty_project'")
    assert "arcane migrate org-scope" in body

    _cli(arcane, "migrate", "org-scope", "--apply")
    [(org,)] = arcane.sql("SELECT org FROM memories WHERE title = 'Legacy'")
    assert org == "personal"
