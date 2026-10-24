"""E2E: an import that cannot reach its source is an error, not "0 ingested"."""

from __future__ import annotations

from tests.e2e.conftest import Arcane, Client

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
