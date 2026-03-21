"""Tests that all CLI commands have help text and are reachable."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from arcane.cli import main


@pytest.fixture
def runner():
    return CliRunner()


class TestCLIHelp:
    """Verify all commands are reachable and have help text."""

    COMMANDS = [
        [],
        ["init", "--help"],
        ["save", "--help"],
        ["search", "--help"],
        ["details", "--help"],
        ["delete", "--help"],
        ["context", "--help"],
        ["reindex", "--help"],
        ["sessions", "--help"],
        ["stats", "--help"],
        ["mcp", "--help"],
        ["journey", "--help"],
        ["journey", "start", "--help"],
        ["journey", "update", "--help"],
        ["journey", "complete", "--help"],
        ["journey", "list", "--help"],
        ["journey", "show", "--help"],
        ["link", "--help"],
        ["trace", "--help"],
        ["migrate", "--help"],
        ["migrate", "echovault", "--help"],
        ["migrate", "check", "--help"],
        ["config", "--help"],
        ["config", "set-home", "--help"],
        ["config", "clear-home", "--help"],
        ["ingest", "--help"],
        ["ingest", "git", "--help"],
        ["ingest", "gha", "--help"],
        ["ingest", "linear", "--help"],
        ["analyze", "--help"],
        ["analyze", "flakes", "--help"],
        ["analyze", "velocity", "--help"],
        ["draft", "--help"],
        ["draft", "blog", "--help"],
        ["draft", "adr", "--help"],
    ]

    @pytest.mark.parametrize("args", COMMANDS, ids=[" ".join(a) or "root" for a in COMMANDS])
    def test_command_help(self, runner, args):
        if not args:
            args = ["--help"]
        result = runner.invoke(main, args)
        assert result.exit_code == 0, f"Command failed: arcane {' '.join(args)}\n{result.output}"
