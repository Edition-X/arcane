"""Arcane — Unified engineering intelligence platform."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("arcane-mcp")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0+unknown"
