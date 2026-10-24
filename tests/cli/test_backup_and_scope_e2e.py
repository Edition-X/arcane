"""End-to-end: the real CLI against a real store, a real git repo and real archives."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from arcane.cli import main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("context:\n  semantic: never\n", encoding="utf-8")
    monkeypatch.setenv("ARCANE_HOME", str(home))
    return home


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _arcane(*args: str) -> str:
    result = CliRunner().invoke(main, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_worktree_of_repo_without_remote_saves_to_main_checkout_project(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_checkout = tmp_path / "code" / "Emergence"
    main_checkout.mkdir(parents=True)
    _git(main_checkout, "init", "-q")
    _git(main_checkout, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    worktree = tmp_path / "worktrees" / "Emergence" / "t3code-72abab4d"
    _git(main_checkout, "worktree", "add", "-q", str(worktree))

    monkeypatch.chdir(worktree)
    _arcane("save", "--title", "from the worktree", "--what", "w")
    monkeypatch.chdir(main_checkout)
    _arcane("save", "--title", "from the main checkout", "--what", "m")

    output = _arcane("projects")
    assert "2  emergence" in output
    assert "t3code" not in output


def test_backup_archives_a_consistent_store_and_rotates(home: Path, tmp_path: Path) -> None:
    _arcane("save", "--title", "keep this safe", "--what", "a memory worth a backup", "--project", "demo")
    dest = tmp_path / "backups"

    for _ in range(3):
        output = _arcane("backup", "--dest", str(dest), "--keep", "2")
    assert "Backed up 1 memories" in output
    assert "removed old backup" in output

    archives = sorted(dest.glob("arcane-*.tar.gz"))
    assert len(archives) == 2
    assert not list(dest.glob("*.partial"))

    restored = tmp_path / "restored"
    with tarfile.open(archives[-1]) as tar:
        names = tar.getnames()
        tar.extractall(restored, filter="data")
    assert "index.db" in names
    assert any(n.startswith("vault/demo/") for n in names)
    assert not any(n.endswith(".lock") for n in names)

    conn = sqlite3.connect(restored / "index.db")
    try:
        titles = [row[0] for row in conn.execute("SELECT title FROM memories")]
    finally:
        conn.close()
    assert titles == ["keep this safe"]


def test_backup_defaults_to_home_backups(home: Path) -> None:
    _arcane("save", "--title", "t", "--what", "w", "--project", "demo")
    _arcane("backup")
    assert len(list((home / "backups").glob("arcane-*.tar.gz"))) == 1


def test_backup_without_a_store_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCANE_HOME", os.fspath(tmp_path / "empty"))
    result = CliRunner().invoke(main, ["backup", "--dest", os.fspath(tmp_path / "b")])
    assert result.exit_code != 0
    assert "no database" in result.output
