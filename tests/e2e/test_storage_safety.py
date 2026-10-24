"""Regression scenarios through real MCP/CLI processes and real SQLite stores."""

from __future__ import annotations

import asyncio
import sqlite3
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client


def cli(arcane: Arcane, *args: str, home: Path | None = None) -> str:
    result = subprocess.run(
        [ARCANE, *args],
        cwd=arcane.repo,
        env={**arcane.env("full"), "ARCANE_HOME": str(home or arcane.home)},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_concurrent_servers_merge_one_title_without_losing_details_or_tags(arcane: Arcane) -> None:
    async def scenario(c: Client, server: int) -> list[dict[str, Any]]:
        return await asyncio.gather(
            *(
                c.call(
                    "memory_save",
                    title="Shared decision",
                    what="latest decision",
                    tags=[f"tag-{server}-{i}"],
                    details=f"DETAIL-{server}-{i}",
                )
                for i in range(6)
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(arcane.run, lambda c, n=n: scenario(c, n)) for n in range(2)]
        saved = [item for future in futures for item in future.result()]
    assert len({item["id"] for item in saved}) == 1
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(1,)]
    content = Path(saved[0]["file_path"]).read_text()
    assert content.count("### Shared decision") == 1
    tags = arcane.sql("SELECT tags FROM memories")[0][0]
    for n in range(2):
        for i in range(6):
            assert f"tag-{n}-{i}" in tags
            assert f"DETAIL-{n}-{i}" in content


def test_updates_and_duplicate_saves_refresh_the_same_markdown_section(arcane: Arcane) -> None:
    async def scenario(c: Client) -> str:
        saved = await c.call("memory_save", title="Mutable note", what="OLD-CONTENT", details="First details")
        await c.call("memory_update", memory_id=saved["id"], what="UPDATED-CONTENT", details_append="More details")
        content = Path(saved["file_path"]).read_text()
        assert "OLD-CONTENT" not in content
        assert "UPDATED-CONTENT" in content and "More details" in content
        merged = await c.call("memory_save", title="Mutable note", what="MERGED-CONTENT", details="Merged details")
        assert merged["id"] == saved["id"]
        return saved["file_path"]

    content = Path(arcane.run(scenario)).read_text()
    assert "UPDATED-CONTENT" not in content
    assert "MERGED-CONTENT" in content and "Merged details" in content
    assert content.count("### Mutable note") == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_deletion_covers_headings_in_details_and_preserves_neighbours(arcane: Arcane, legacy: bool) -> None:
    async def scenario(c: Client) -> str:
        doomed = await c.call(
            "memory_save",
            title="Remove this",
            what="Doomed note",
            details="intro\n## Nested heading\nDELETE-TAIL\n```md\n### example\n```",
            category="decision",
        )
        await c.call("memory_save", title="Keep this", what="Retained note", category="decision")
        path = Path(doomed["file_path"])
        if legacy:
            path.write_text(path.read_text().replace(f"<!-- /arcane-memory:{doomed['id']} -->", ""))
        await c.call("memory_delete", memory_id=doomed["id"])
        return str(path)

    content = Path(arcane.run(scenario)).read_text()
    assert "Remove this" not in content and "DELETE-TAIL" not in content
    assert "### Keep this" in content and "Retained note" in content


@pytest.mark.parametrize("legacy", [False, True])
def test_restored_store_never_modifies_original_vault(arcane: Arcane, tmp_path: Path, legacy: bool) -> None:
    async def save(c: Client) -> dict[str, Any]:
        return await c.call("memory_save", title="Restore me", what="Separate stores")

    saved = arcane.run(save)
    source = Path(saved["file_path"])
    if legacy:
        arcane.sql("UPDATE memories SET file_path = ?", (str(source),))
    before = source.read_bytes()
    backup_dir = tmp_path / "backups"
    cli(arcane, "backup", "--dest", str(backup_dir))
    restored = tmp_path / "restored"
    with tarfile.open(next(backup_dir.glob("*.tar.gz"))) as archive:
        archive.extractall(restored, filter="data")
    cli(arcane, "delete", saved["id"], home=restored)
    assert source.read_bytes() == before
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(1,)]
    restored_file = restored / source.relative_to(arcane.home)
    assert "Restore me" not in restored_file.read_text()


def test_org_traversal_is_rejected_without_creating_outside_files(arcane: Arcane, tmp_path: Path) -> None:
    async def scenario(c: Client) -> None:
        error = await c.error(
            "memory_save", title="Escape attempt", what="must reject", scope="org", org="x/../../../escaped"
        )
        assert "does not match" in error.lower() or "org" in error.lower()

    arcane.run(scenario)
    assert not (tmp_path / "escaped").exists()
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(0,)]


def test_advertised_save_constraints_are_enforced_before_persistence(arcane: Arcane) -> None:
    async def scenario(c: Client) -> None:
        tools = (await c.session.list_tools()).tools
        schema = next(tool.input_schema for tool in tools if tool.name == "memory_save")
        assert schema["properties"]["title"]["maxLength"] == 60
        assert "source" in schema["properties"]
        assert "too long" in await c.error("memory_save", title="x" * 61, what="invalid")
        assert "minimum" in await c.error("memory_save", title="Invalid confidence", what="invalid", confidence=-0.1)

    arcane.run(scenario)
    assert arcane.sql("SELECT COUNT(*) FROM memories") == [(0,)]


def test_migration_includes_committed_wal_rows(arcane: Arcane, tmp_path: Path) -> None:
    cli(arcane, "save", "--title", "Checkpointed note", "--what", "initial state")
    reader = sqlite3.connect(arcane.home / "index.db")
    try:
        reader.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM memories").fetchone()
        cli(arcane, "save", "--title", "WAL note", "--what", "committed after reader snapshot")
        target = tmp_path / "migrated"
        output = cli(arcane, "migrate", "echovault", "--source", str(arcane.home), home=target)
        assert "2 memories" in output
        with sqlite3.connect(target / "index.db") as db:
            assert db.execute("SELECT COUNT(*) FROM memories").fetchone() == (2,)
    finally:
        reader.close()


def test_sessions_lists_new_org_layout_and_legacy_files(arcane: Arcane) -> None:
    cli(arcane, "save", "--title", "Session note", "--what", "current layout")
    legacy = arcane.home / "vault" / "legacy" / "2020-01-01-session.md"
    legacy.parent.mkdir()
    legacy.write_text("# Old session\n")
    output = cli(arcane, "sessions")
    assert "@acme/widget" in output and "legacy" in output
    output = cli(arcane, "sessions", "--project", "widget")
    assert "@acme/widget" in output and "legacy" not in output
