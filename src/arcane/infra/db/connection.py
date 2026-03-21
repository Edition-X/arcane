"""SQLite connection management with FTS5 and sqlite-vec support."""

from __future__ import annotations

from typing import Any

try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3  # type: ignore[no-redef]

import sqlite_vec


class Database:
    """Manages a SQLite connection with extensions loaded."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.cursor().execute(sql, params)

    def executemany(self, sql: str, params: list[tuple]) -> sqlite3.Cursor:
        return self.conn.cursor().executemany(sql, params)

    def fetchone(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        cursor = self.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
