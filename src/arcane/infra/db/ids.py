"""Safe resolution of user-supplied entity IDs."""

from __future__ import annotations

from typing import cast

from arcane.infra.db.connection import Database

MIN_PREFIX_LENGTH = 8
_TABLES = {"memories", "journeys", "insights", "artifacts", "relationships"}


class IdentifierResolutionError(ValueError):
    """A supplied ID cannot safely identify one entity."""


def resolve_unique_id(db: Database, table: str, value: str) -> str | None:
    """Resolve an exact ID or an unambiguous, safe prefix.

    Prefixes are an MCP/CLI convenience, not a wildcard search API. Rejecting
    short and ambiguous values prevents an agent from mutating an arbitrary
    first row returned by SQLite.
    """
    if table not in _TABLES:
        raise ValueError(f"Unsupported entity table: {table}")

    candidate = value.strip()
    if not candidate:
        raise IdentifierResolutionError("ID must not be empty.")

    exact = db.fetchone(f"SELECT id FROM {table} WHERE id = ?", (candidate,))
    if exact:
        return cast(str, exact["id"])

    if any(char in candidate for char in ("%", "_", "*")):
        raise IdentifierResolutionError("ID prefixes cannot contain wildcard characters.")
    if len(candidate) < MIN_PREFIX_LENGTH:
        raise IdentifierResolutionError(f"ID prefix must be at least {MIN_PREFIX_LENGTH} characters.")

    matches = db.fetchall(f"SELECT id FROM {table} WHERE id LIKE ? LIMIT 2", (candidate + "%",))
    if not matches:
        return None
    if len(matches) > 1:
        raise IdentifierResolutionError("ID prefix is ambiguous; provide more characters.")
    return cast(str, matches[0]["id"])
