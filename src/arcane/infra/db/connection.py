"""SQLite connection management with FTS5 and sqlite-vec support."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3

import sqlite_vec

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 10_000

# pysqlite3-binary only ships Linux x86_64 wheels, so it cannot be the only
# advice: the python.org build for macOS is the usual way to land here.
_NO_EXTENSIONS_WARNING = (
    "This Python cannot load SQLite extensions, so sqlite-vec is unavailable and "
    "search will use keyword matching only. To restore semantic search, reinstall "
    "Arcane on a Python that can, such as one from Homebrew or `uv python install`, "
    'or on Linux x86_64 add the pysqlite3 extra: pip install "arcane-mcp[pysqlite3]"'
)

_warned_about_extensions = False


def load_vec_extension(conn: Any) -> bool:
    """Load sqlite-vec into *conn*, returning whether it is usable.

    Several Python distributions — the python.org installer for macOS among
    them — are compiled without ``--enable-loadable-sqlite-extensions``, so
    ``enable_load_extension`` does not exist. Arcane stays useful without vectors: search falls back to FTS5,
    exactly as it already does when no embedder is reachable. Failing to start
    at all would be the wrong trade.
    """
    global _warned_about_extensions
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        if not _warned_about_extensions:
            logger.warning(_NO_EXTENSIONS_WARNING)
            _warned_about_extensions = True
        return False
    try:
        sqlite_vec.load(conn)
    except sqlite3.Error as exc:
        if not _warned_about_extensions:
            logger.warning("sqlite-vec failed to load (%s). %s", exc, _NO_EXTENSIONS_WARNING)
            _warned_about_extensions = True
        return False
    finally:
        conn.enable_load_extension(False)
    return True


class Database:
    """Manages a SQLite connection with extensions loaded.

    ``vec_available`` reports whether sqlite-vec loaded. When it did not, the
    store works normally minus vector similarity.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=BUSY_TIMEOUT_MS / 1000)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._transaction_depth = 0

        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

        self.vec_available = load_vec_extension(self.conn)

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.cursor().execute(sql, params)

    def executemany(self, sql: str, params: list[tuple]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.cursor().executemany(sql, params)

    def fetchone(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        with self._lock:
            cursor = self.conn.cursor().execute(sql, params)
            row = cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self.conn.cursor().execute(sql, params)
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def commit(self) -> None:
        with self._lock:
            if self._transaction_depth == 0:
                self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize a complete write operation and commit it atomically.

        Repository methods retain their standalone ``commit()`` calls, but
        those become no-ops inside this context. Nested service calls use
        savepoints so they can safely participate in an outer unit of work.
        """
        with self._lock:
            outermost = self._transaction_depth == 0
            savepoint = f"arcane_tx_{self._transaction_depth}"
            if outermost:
                self.conn.execute("BEGIN IMMEDIATE")
            else:
                self.conn.execute(f"SAVEPOINT {savepoint}")
            self._transaction_depth += 1
            try:
                yield
            except Exception:
                if outermost:
                    self.conn.rollback()
                else:
                    self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                if outermost:
                    self.conn.commit()
                else:
                    self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._transaction_depth -= 1

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def backup(self, destination: str) -> None:
        """Write a consistent SQLite backup, including pending WAL changes."""
        with self._lock:
            target = sqlite3.connect(destination)
            try:
                self.conn.backup(target)
            finally:
                target.close()
