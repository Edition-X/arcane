"""Tests for package and runtime version identity."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from arcane import __version__


def test_distribution_version_matches_runtime_version():
    assert importlib.metadata.version("arcane-mcp") == __version__


def test_install_docs_do_not_reference_unrelated_pypi_package():
    root = Path(__file__).parents[2]
    for path in (root / "README.md", root / "docs" / "README.md", root / "docs" / "installation.md"):
        content = path.read_text()
        assert "uv tool install arcane\n" not in content
        assert "pip install arcane\n" not in content
