"""E2E: an import that cannot reach its source is an error, not "0 ingested"."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client

# Every request goes to a closed local port, so the fetch fails fast and offline.
DEAD_PROXY = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}


def test_github_actions_import_reports_why_it_failed(arcane: Arcane) -> None:
    async def scenario(c: Client) -> str:
        return await c.error("ingest_gha", owner="acme", repo="widget")

    error = arcane.run(scenario, extra_env=DEAD_PROXY)
    assert "GitHub Actions runs for acme/widget could not be fetched after 3 attempts" in error
    assert "network error" in error
    assert "GITHUB_TOKEN is not set" in error
    assert arcane.sql("SELECT count(*) FROM artifacts")[0][0] == 0


def test_linear_import_without_a_key_says_so(arcane: Arcane) -> None:
    async def scenario(c: Client) -> str:
        return await c.error("ingest_linear", team_id="INF")

    assert (
        arcane.run(scenario, extra_env=DEAD_PROXY) == "LINEAR_API_KEY is not set, so Linear issues cannot be fetched."
    )


@pytest.mark.parametrize("path_kind", ["missing", "not-repository", "file", "empty-repository"])
def test_git_source_errors_fail_cli_and_mcp(arcane: Arcane, tmp_path: Path, path_kind: str) -> None:
    path = tmp_path / path_kind
    if path_kind in {"not-repository", "empty-repository"}:
        path.mkdir()
    elif path_kind == "file":
        path.write_text("not a directory", encoding="utf-8")
    if path_kind == "empty-repository":
        subprocess.run(["git", "init", "-q", str(path)], check=True)
    output = subprocess.run(
        [ARCANE, "ingest", "git", "--repo-path", str(path)],
        cwd=arcane.repo,
        env=arcane.env("full"),
        capture_output=True,
        text=True,
    )
    assert output.returncode != 0
    assert str(path) in output.stderr and "--repo-path" in output.stderr
    assert "0 ingested" not in output.stdout

    async def scenario(c: Client) -> str:
        return await c.error("ingest_git", repo_path=str(path))

    error = arcane.run(scenario)
    assert str(path) in error and "--repo-path" in error
    assert arcane.sql("SELECT count(*) FROM artifacts")[0][0] == 0


def test_git_not_on_path_reports_install_hint(arcane: Arcane, tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = {"PATH": str(empty_bin)}
    output = subprocess.run(
        [ARCANE, "ingest", "git"],
        cwd=arcane.repo,
        env={**arcane.env("full"), **env},
        capture_output=True,
        text=True,
    )
    assert output.returncode != 0 and "Install git" in output.stderr

    async def scenario(c: Client) -> str:
        return await c.error("ingest_git")

    assert "Install git" in arcane.run(scenario, extra_env=env)
