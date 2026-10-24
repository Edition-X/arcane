"""Tests for package and runtime version identity."""

from __future__ import annotations

import importlib.metadata

from arcane import __version__


def test_distribution_version_matches_runtime_version():
    assert importlib.metadata.version("arcane-mcp") == __version__
