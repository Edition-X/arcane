"""Backups — a consistent snapshot of the store, archived with the markdown vault.

The database is copied through SQLite's online backup API, so a snapshot taken
while an MCP server is writing is still consistent (a plain file copy of a WAL
database is not). Each backup is one ``arcane-<UTC timestamp>.tar.gz`` holding
``index.db`` and ``vault/``; restoring is unpacking it into ``ARCANE_HOME``.
"""

from __future__ import annotations

import os
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlite_vec

ARCHIVE_PREFIX = "arcane-"
ARCHIVE_SUFFIX = ".tar.gz"


class BackupError(RuntimeError):
    """The store could not be snapshotted, or the snapshot failed its check."""


@dataclass(frozen=True)
class BackupResult:
    path: str
    memories: int
    size_bytes: int
    pruned: list[str]


def _check_snapshot(db_path: str) -> int:
    """Integrity-check a snapshot and return its memory count."""
    conn = sqlite3.connect(db_path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        status = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            raise BackupError(f"snapshot failed integrity_check: {status}")
        count: int = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        # Reads the vector table, which a broken vec0 shadow table fails. It
        # only exists once a memory has been embedded.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memories_vec'").fetchone():
            conn.execute("SELECT count(*) FROM memories_vec").fetchone()
        return count
    except sqlite3.Error as exc:
        raise BackupError(f"snapshot is unreadable: {exc}") from exc
    finally:
        conn.close()


def _skip_locks(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Leave out the vault's per-file ``.lock`` files; they are runtime state."""
    return None if info.name.endswith(".lock") else info


def _prune(dest: str, keep: int) -> list[str]:
    """Delete all but the newest *keep* archives in *dest*; return what was removed."""
    archives = sorted(
        (name for name in os.listdir(dest) if name.startswith(ARCHIVE_PREFIX) and name.endswith(ARCHIVE_SUFFIX)),
        key=lambda name: (os.path.getmtime(os.path.join(dest, name)), name),
    )
    stale = archives[:-keep] if keep > 0 else []
    for name in stale:
        os.remove(os.path.join(dest, name))
    return stale


def create_backup(home: str, dest: str, *, keep: int = 14) -> BackupResult:
    """Snapshot ``home``'s database and vault into a new archive in *dest*.

    The archive is written under a temporary name and renamed into place, so a
    failed run never leaves a partial file that rotation would count. Only the
    newest *keep* archives are kept (``0`` keeps everything).
    """
    db_path = os.path.join(home, "index.db")
    if not os.path.exists(db_path):
        raise BackupError(f"no database at {db_path}")
    os.makedirs(dest, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = os.path.join(dest, f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}")
    n = 1
    while os.path.exists(archive):
        archive = os.path.join(dest, f"{ARCHIVE_PREFIX}{stamp}-{n}{ARCHIVE_SUFFIX}")
        n += 1

    with tempfile.TemporaryDirectory(prefix="arcane-backup-") as work:
        snapshot = os.path.join(work, "index.db")
        try:
            src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(snapshot)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except sqlite3.Error as exc:
            raise BackupError(f"could not snapshot {db_path}: {exc}") from exc
        memories = _check_snapshot(snapshot)

        partial = archive + ".partial"
        try:
            with tarfile.open(partial, "w:gz") as tar:
                tar.add(snapshot, arcname="index.db")
                vault = os.path.join(home, "vault")
                if os.path.isdir(vault):
                    tar.add(vault, arcname="vault", filter=_skip_locks)
            os.replace(partial, archive)
        finally:
            if os.path.exists(partial):
                os.remove(partial)

    return BackupResult(
        path=archive,
        memories=memories,
        size_bytes=os.path.getsize(archive),
        pruned=_prune(dest, keep),
    )
