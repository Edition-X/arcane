"""E2E: installed entry-point distributions execute through CLI and MCP."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client

# A small, valid wheel installed into an isolated target; no registry patching or
# fake metadata. Both entry points discover the installed distribution normally.
PLUGIN_SOURCE = '''
from datetime import datetime, timezone
import uuid

class Importer:
    """Import a local text artifact."""
    name = "local_text"
    def __init__(self, title="Local artifact"):
        self.title = title
    def supports_incremental(self):
        return True
    def ingest(self, project, since=None):
        return [{"id": str(uuid.uuid4()), "artifact_type": "document",
                 "external_id": self.title, "title": self.title, "project": project,
                 "created_at": datetime.now(timezone.utc).isoformat(), "raw_data": {"source": "entry point"}}]

class Analyzer:
    """Count real artifacts in the injected store."""
    name = "local_count"
    def __init__(self, artifact_repo=None, label="Artifact count", org=None):
        self.repo = artifact_repo
        self.label = label
        self.org = org
    def analyze(self, project):
        count = len(self.repo.list_all(project=project, org=self.org))
        return [{"id": str(uuid.uuid4()), "insight_type": "local_count", "title": self.label,
                 "body": str(count), "severity": "info", "project": project,
                 "created_at": datetime.now(timezone.utc).isoformat(), "metadata": {}}]

class Writer:
    """Generate a local text brief."""
    name = "local_brief"
    def __init__(self, prefix="Brief"):
        self.prefix = prefix
    def generate(self, context):
        if context["topic"] == "scope":
            return context["org"] + "/" + context["project"]
        return self.prefix + ": " + context["topic"]
'''


@pytest.fixture
def installed_plugins(tmp_path: Path) -> dict[str, str]:
    wheel = tmp_path / "arcane_e2e_plugins-1.0-py3-none-any.whl"
    metadata = "arcane_e2e_plugins-1.0.dist-info"
    files = {
        "arcane_e2e_plugins.py": PLUGIN_SOURCE,
        f"{metadata}/METADATA": "Metadata-Version: 2.1\nName: arcane-e2e-plugins\nVersion: 1.0\n",
        f"{metadata}/WHEEL": "Wheel-Version: 1.0\nGenerator: arcane-e2e\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{metadata}/entry_points.txt": (
            "[arcane.plugins.ingestion]\nlocal_text = arcane_e2e_plugins:Importer\n"
            "[arcane.plugins.intelligence]\nlocal_count = arcane_e2e_plugins:Analyzer\n"
            "[arcane.plugins.content]\nlocal_brief = arcane_e2e_plugins:Writer\n"
        ),
    }
    files[f"{metadata}/RECORD"] = "".join(f"{name},,\n" for name in [*files, f"{metadata}/RECORD"])
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    target = tmp_path / "installed"
    subprocess.run(
        ["uv", "pip", "install", "--python", sys.executable, "--no-deps", "--target", str(target), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"PYTHONPATH": str(target)}


def cli(arcane: Arcane, env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ARCANE, *args],
        cwd=arcane.repo,
        env={**arcane.env("full"), **env},
        capture_output=True,
        text=True,
        check=check,
    )


def test_installed_plugins_are_discovered_and_run_via_cli(arcane: Arcane, installed_plugins: dict[str, str]) -> None:
    env = installed_plugins
    for group, name in (("ingest", "local_text"), ("analyze", "local_count"), ("draft", "local_brief")):
        assert name in cli(arcane, env, group, "--help").stdout
        assert name in cli(arcane, env, group, "--list").stdout
        help_text = cli(arcane, env, group, name, "--help").stdout
        assert "Constructor options" in help_text and "--options" in help_text
    out = cli(arcane, env, "ingest", "local_text", "--options", '{"title":"CLI artifact"}')
    assert json.loads(out.stdout)["ingested"] == 1
    out = cli(arcane, env, "analyze", "local_count", "--options", '{"label":"CLI count"}')
    assert json.loads(out.stdout)["insights_created"] == 1
    assert arcane.sql("SELECT title, body FROM insights WHERE insight_type='local_count'") == [("CLI count", "1")]
    assert arcane.sql("SELECT title FROM artifacts") == [("CLI artifact",)]
    assert (
        cli(
            arcane,
            env,
            "draft",
            "local_brief",
            "--options",
            '{"prefix":"Note"}',
            "--context",
            '{"topic":"installed plugins"}',
        ).stdout
        == "Note: installed plugins\n"
    )
    assert (
        cli(
            arcane,
            env,
            "draft",
            "local_brief",
            "--project",
            "widget",
            "--context",
            '{"topic":"scope","org":"foreign","project":"foreign"}',
        ).stdout
        == "acme/widget\n"
    )
    bad = cli(arcane, env, "ingest", "local_text", "--options", '{"unknown":true}', check=False)
    assert bad.returncode != 0 and "Cannot configure" in bad.stderr
    bad_json = cli(arcane, env, "draft", "local_brief", "--context", "[]", check=False)
    assert bad_json.returncode != 0 and "JSON object" in bad_json.stderr


def test_installed_plugins_are_discovered_and_run_via_mcp(arcane: Arcane, installed_plugins: dict[str, str]) -> None:
    async def scenario(c: Client) -> None:
        discovered = await c.call("plugins")
        assert {p["name"] for p in discovered["ingestion"]} >= {"git", "local_text"}
        assert "title" in next(p for p in discovered["ingestion"] if p["name"] == "local_text")["options"]
        tools = (await c.session.list_tools()).tools
        analyze = next(t for t in tools if t.name == "analyze")
        assert "local_count" in analyze.input_schema["properties"]["plugin_name"]["enum"]
        journey = await c.call("journey_start", title="Plugin import")
        imported = await c.call(
            "plugins",
            kind="ingestion",
            plugin_name="local_text",
            options={"title": "MCP artifact"},
            journey_id=journey["id"],
        )
        assert imported["ingested"] == 1
        again = await c.call("plugins", kind="ingestion", plugin_name="local_text", options={"title": "MCP artifact"})
        assert again["skipped"] == 1
        assert (await c.call("analyze", plugin_name="local_count"))["insights_created"] == 1
        assert (
            await c.call("plugins", kind="intelligence", plugin_name="local_count", options={"label": "MCP count"})
        )["insights_created"] == 1
        draft = await c.call(
            "plugins",
            kind="content",
            plugin_name="local_brief",
            options={"prefix": "Note"},
            context={"topic": "MCP plugin"},
        )
        assert draft["brief"] == "Note: MCP plugin"
        scoped = await c.call(
            "plugins",
            kind="content",
            plugin_name="local_brief",
            project="widget",
            context={"topic": "scope", "org": "other", "project": "foreign"},
        )
        assert scoped["brief"] == "acme/widget"
        assert "Available:" in await c.error("plugins", kind="content", plugin_name="missing")
        assert "Cannot configure" in await c.error(
            "plugins", kind="content", plugin_name="local_brief", options={"bad": 1}
        )
        assert "Provide kind" in await c.error("plugins", plugin_name="local_brief")
        assert "cannot be overridden" in await c.error(
            "plugins", kind="intelligence", plugin_name="local_count", options={"org": "other"}
        )

    arcane.run(scenario, extra_env=installed_plugins)
    assert arcane.sql("SELECT title FROM artifacts") == [("MCP artifact",)]
    assert arcane.sql("SELECT body FROM insights WHERE insight_type='local_count'") == [("1",), ("1",)]
    assert arcane.sql("SELECT count(*) FROM relationships WHERE source_type='artifact'")[0][0] == 1


def test_health_respects_org_global_and_duplicate_title_scopes(arcane: Arcane) -> None:
    async def seed(c: Client) -> None:
        for org, project in (("acme", "widget"), ("other", "widget"), ("acme", "other"), ("acme", ""), ("global", "")):
            await c.call("memory_save", title="Shared title", what="Valid scoped memory", org=org, project=project)

    async def audit(c: Client) -> None:
        await c.call("analyze", plugin_name="health")

    arcane.run(seed)
    # Equivalent raw project spellings in different orgs are not fragmentation.
    arcane.sql("UPDATE memories SET project='Widget' WHERE org='other'")
    arcane.run(audit)
    assert not arcane.sql("SELECT insight_type FROM insights WHERE severity='warning'")
    summary = arcane.sql("SELECT body FROM insights WHERE insight_type='health'")[0][0]
    assert "Memories:            3" in summary
    # Equal titles in other projects/orgs must not inflate duplicate counts.
    arcane.sql("UPDATE memories SET project='Widget' WHERE org='acme' AND project='other'")
    arcane.sql("UPDATE memories SET title=' Shared title ' WHERE org='acme' AND project='Widget'")
    # Move it into the same scope to exercise the normalized duplicate grouping.
    arcane.sql("UPDATE memories SET project='widget' WHERE org='acme' AND project='Widget'")

    arcane.run(audit)
    duplicates = arcane.sql("SELECT body FROM insights WHERE insight_type='health_duplicate_titles'")
    assert len(duplicates) == 1 and "x2" in duplicates[0][0] and "acme/widget" in duplicates[0][0]
