"""Typed results shared by memory services and their public interfaces."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class MemorySaveResult(TypedDict):
    id: str
    file_path: str
    action: Literal["created", "updated"]
    warnings: list[str]
    scope: NotRequired[dict[str, str]]
