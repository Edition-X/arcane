"""E2E: what the CLI shows a user, driven through the installed `arcane` command."""

from __future__ import annotations

import subprocess

from tests.e2e.conftest import ARCANE, Arcane


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
