"""Tests for package and runtime version identity."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from arcane import __version__


def test_distribution_version_matches_runtime_version():
    assert importlib.metadata.version("arcane-mcp") == __version__


def test_install_docs_do_not_reference_unrelated_pypi_package():
    root = Path(__file__).parents[2]
    expected_uv_command = (
        'uv tool install --from "git+https://github.com/Edition-X/arcane.git@v0.2.0-beta.11" '
        'arcane-mcp'
    )
    for path in (root / "README.md", root / "docs" / "README.md", root / "docs" / "installation.md"):
        content = path.read_text()
        assert "uv tool install arcane\n" not in content
        assert "pip install arcane\n" not in content
        assert expected_uv_command in content
        assert "git+https://github.com/Edition-X/arcane.git@v0.2.0-beta.10" not in content
        assert "v0.2.0-beta.11" in content
