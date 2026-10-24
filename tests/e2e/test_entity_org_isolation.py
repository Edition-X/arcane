"""Non-memory ownership through real MCP sessions and the CLI, including upgrades."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client, git


def _cli(arcane: Arcane, *args: str) -> str:
    return subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True, check=True
    ).stdout


def test_same_project_keeps_entity_ownership_and_external_ids_separate(arcane: Arcane, tmp_path: Path) -> None:
    beta = tmp_path / "beta"
    git(tmp_path, "clone", "-q", str(arcane.repo), str(beta))
    git(beta, "remote", "set-url", "origin", "git@github.com:Beta/widget.git")

    async def populate(c: Client) -> dict[str, Any]:
        j = await c.call("journey_start", title="Own investigation")
        m = await c.call("memory_save", title="Own context", what="Private", journey_id=j["id"])
        ingest = await c.call("ingest_git", journey_id=j["id"])
        analysis = await c.call("analyze", plugin_name="velocity")
        artifacts = await c.call("artifact_search", query="change")
        await c.call("journey_complete", journey_id=j["id"], summary="Done")
        return {"journey": j, "memory": m, "ingest": ingest, "analysis": analysis, "artifacts": artifacts}

    acme = arcane.run(populate)
    other = arcane.run(populate, cwd=beta)
    assert acme["ingest"]["ingested"] == other["ingest"]["ingested"] == 2
    assert len(acme["artifacts"]) == len(other["artifacts"]) == 2
    assert {a["id"] for a in acme["artifacts"]}.isdisjoint(a["id"] for a in other["artifacts"])
    assert arcane.sql("SELECT org, count(*) FROM artifacts GROUP BY org ORDER BY org") == [("acme", 2), ("beta", 2)]
    assert arcane.sql("SELECT org, count(*) FROM insights GROUP BY org ORDER BY org") == [("acme", 1), ("beta", 1)]
    beta_insight = arcane.sql("SELECT id FROM insights WHERE org = 'beta'")[0][0]
    # Old stores may already have invalid links. They must not expose foreign
    # titles or even IDs through a scoped journey/export.
    arcane.sql(
        "INSERT INTO relationships VALUES ('cross-org-edge', 'journey', ?, 'memory', ?, 'related_to', '2026-01-01')",
        (acme["journey"]["id"], other["memory"]["id"]),
    )

    async def inspect(c: Client) -> dict[str, Any]:
        foreign = other["journey"]["id"]
        errors = [
            await c.error("journey_show", journey_id=foreign),
            await c.error("journey_update", journey_id=foreign, summary="Overwrite"),
            await c.error("journey_complete", journey_id=foreign),
            await c.error("journey_abandon", journey_id=foreign),
            await c.error("journey_delete", journey_id=foreign),
            await c.error("artifact_details", artifact_id=other["artifacts"][0]["id"]),
            await c.error("insights_ack", insight_id=beta_insight),
            await c.error("ingest_git", journey_id=foreign),
        ]
        return {
            "errors": errors,
            "journeys": await c.call("journey_list"),
            "insights": await c.call("insights"),
            "artifacts": await c.call("artifact_search", query="change"),
            "show": await c.call("journey_show", journey_id=acme["journey"]["id"]),
        }

    seen = arcane.run(inspect)
    assert all("not found" in error.lower() for error in seen["errors"])
    assert [j["id"] for j in seen["journeys"]] == [acme["journey"]["id"]]
    assert beta_insight not in {i["id"] for i in seen["insights"]}
    assert {a["id"] for a in seen["artifacts"]} == {a["id"] for a in acme["artifacts"]}
    assert [m["memory_id"] for m in seen["show"]["linked_memories"]] == [acme["memory"]["id"]]
    assert "not found" in _cli(arcane, "artifact", "show", other["artifacts"][0]["id"])
    assert other["journey"]["id"][:12] not in _cli(arcane, "journey", "list", "--project")
    destination = tmp_path / "acme.json"
    _cli(arcane, "export", "--org", "acme", "--out", str(destination))
    exported = json.loads(destination.read_text())
    for entity in ("memories", "journeys", "artifacts", "insights"):
        assert exported[entity]
        assert {r["org"] for r in exported[entity]} == {"acme"}
    assert "cross-org-edge" not in {r["id"] for r in exported["relationships"]}
    report = json.loads(_cli(arcane, "report", "--org", "acme", "--format", "json"))
    journey_ids = {e["id"] for p in report["projects"] for e in p["entries"] if e["kind"] == "journey"}
    assert journey_ids == {acme["journey"]["id"]}


def test_legacy_migration_backfills_only_unambiguous_projects(arcane: Arcane) -> None:
    """Start the real app against a pre-org schema, then restart it twice."""
    # A genuine old-format store: no entity org columns, the old artifact
    # uniqueness constraint, existing FTS content, and a user index/trigger.
    with sqlite3.connect(arcane.home / "index.db") as conn:
        conn.executescript("""
            CREATE TABLE memories (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, what TEXT NOT NULL, why TEXT, impact TEXT, tags TEXT, category TEXT,
                project TEXT NOT NULL, source TEXT, related_files TEXT, file_path TEXT NOT NULL,
                section_anchor TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                org TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE journeys (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                project TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', started_at TEXT NOT NULL,
                completed_at TEXT, summary TEXT, linear_issue_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE artifacts (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, artifact_type TEXT NOT NULL,
                external_id TEXT NOT NULL, title TEXT NOT NULL, url TEXT, raw_data TEXT, project TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(artifact_type, external_id, project)
            );
            CREATE TABLE insights (
                id TEXT PRIMARY KEY, insight_type TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info', project TEXT NOT NULL, metadata TEXT,
                created_at TEXT NOT NULL, acknowledged INTEGER DEFAULT 0
            );
            CREATE VIRTUAL TABLE memories_fts USING fts5(
                title, what, why, impact, tags, category, project, source,
                content='memories', content_rowid='rowid', tokenize='porter unicode61'
            );
            CREATE VIRTUAL TABLE journeys_fts USING fts5(
                title, summary, project, content='journeys', content_rowid='rowid', tokenize='porter unicode61'
            );
            CREATE VIRTUAL TABLE artifacts_fts USING fts5(
                title, artifact_type, external_id, project, raw_data,
                content='artifacts', content_rowid='rowid', tokenize='porter unicode61'
            );
            CREATE INDEX custom_artifact_title ON artifacts(title);
            CREATE TABLE artifact_audit (artifact_id TEXT);
            CREATE TRIGGER custom_artifact_insert AFTER INSERT ON artifacts BEGIN
                INSERT INTO artifact_audit VALUES (new.id);
            END;
        """)
        for project, org in (("owned", "acme"), ("widget", "acme"), ("widget", "beta")):
            conn.execute(
                "INSERT INTO memories (id,title,what,project,org,file_path,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (project + org, "Evidence", "Ownership", project, org, "", "2026-01-01", "2026-01-01"),
            )
        for project in ("owned", "widget", "orphan"):
            conn.execute(
                "INSERT INTO journeys (id,title,project,started_at,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (
                    f"legacy-journey-{project}",
                    "Legacy investigation",
                    project,
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
            conn.execute(
                "INSERT INTO artifacts (id,artifact_type,external_id,title,project,created_at) VALUES (?,?,?,?,?,?)",
                (f"legacy-artifact-{project}", "commit", "same-id", "Legacy artifact", project, "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO insights (id,insight_type,title,body,project,created_at) VALUES (?,?,?,?,?,?)",
                (f"legacy-insight-{project}", "velocity", "Legacy insight", "Body", project, "2026-01-01"),
            )
        conn.execute(
            "INSERT INTO insights (id,insight_type,title,body,project,created_at) VALUES (?,?,?,?,?,?)",
            (
                "legacy-whole-vault",
                "health_stale_journeys",
                "Whole vault",
                "Foreign private titles",
                "owned",
                "2026-01-01",
            ),
        )
        for table in ("memories_fts", "journeys_fts", "artifacts_fts"):
            conn.execute(f"INSERT INTO {table}({table}) VALUES ('rebuild')")
        conn.execute("UPDATE sqlite_sequence SET seq = 100 WHERE name = 'artifacts'")
        before = conn.execute("SELECT rowid, id FROM artifacts ORDER BY rowid").fetchall()

    async def inspect(c: Client) -> dict[str, Any]:
        return {
            "journeys": await c.call("journey_list"),
            "artifacts": await c.call("artifact_search", query="Legacy"),
            "insights": await c.call("insights"),
            "owned": await c.call("artifact_search", query="Legacy", project="owned"),
        }

    seen = arcane.run(inspect)
    assert seen["journeys"] == seen["artifacts"] == seen["insights"] == []
    assert [a["id"] for a in seen["owned"]] == ["legacy-artifact-owned"]
    for table in ("journeys", "artifacts", "insights"):
        assert arcane.sql(f"SELECT project, org FROM {table} WHERE id != 'legacy-whole-vault' ORDER BY project") == [
            ("orphan", ""),
            ("owned", "acme"),
            ("widget", ""),
        ]
    assert arcane.sql("SELECT org FROM insights WHERE id = 'legacy-whole-vault'") == [("",)]
    assert arcane.sql("SELECT rowid, id FROM artifacts ORDER BY rowid") == before
    assert (
        len(
            arcane.sql(
                "SELECT name FROM sqlite_master WHERE name IN ('custom_artifact_title', 'custom_artifact_insert')"
            )
        )
        == 2
    )
    # Losing one owner's evidence later must not retroactively claim unknown rows.
    arcane.sql("DELETE FROM memories WHERE org = 'beta'")
    assert arcane.run(inspect)["artifacts"] == []
    assert arcane.sql("SELECT DISTINCT org FROM artifacts WHERE project = 'widget'") == [("",)]

    async def ingest(c: Client) -> Any:
        return await c.call("ingest_git")

    assert arcane.run(ingest)["ingested"] == 2
    assert arcane.sql("SELECT count(*) FROM artifact_audit")[0][0] == 5
    assert arcane.sql("SELECT MIN(rowid) FROM artifacts WHERE org = 'acme' AND project = 'widget'")[0][0] == 101
    # FTS sync still works after table rebuild and restarts, including deletes.
    arcane.sql("UPDATE artifacts SET title = 'Updated searchable' WHERE id = 'legacy-artifact-owned'")

    async def search_updated(c: Client) -> Any:
        return await c.call("artifact_search", query="searchable", project="owned")

    assert len(arcane.run(search_updated)) == 1
    arcane.sql("DELETE FROM artifacts WHERE id = 'legacy-artifact-owned'")
    assert arcane.run(search_updated) == []


def test_explicit_legacy_recovery_is_backed_up_atomic_and_dry_by_default(arcane: Arcane) -> None:
    async def populate(c: Client) -> Any:
        await c.call("journey_start", title="Known owner")
        return await c.call("ingest_git")

    arcane.run(populate)
    # Unknown legacy records coexist with known acme/widget records. Only the
    # explicit assignment command can claim them after the one-time migration.
    arcane.sql(
        "INSERT INTO journeys (id,title,project,org,started_at,created_at,updated_at) "
        "VALUES ('unknown-journey', 'Recover me', 'widget', '', '2026-01-01', '2026-01-01', '2026-01-01')"
    )
    arcane.sql(
        "INSERT INTO artifacts (id,artifact_type,external_id,title,raw_data,project,org,created_at) "
        "VALUES ('unknown-artifact', 'commit', 'legacy-key', 'Recover artifact', '{\"body\":\"Recover content\"}', "
        "'widget', '', '2026-01-01')"
    )
    arcane.sql(
        "INSERT INTO insights (id,insight_type,title,body,project,org,created_at) "
        "VALUES ('unknown-insight','health','Recover insight','Body','widget','','2026-01-01')"
    )
    args = ("migrate", "entity-org", "--org", "acme", "--project", "widget")
    preview = _cli(arcane, *args)
    assert "Dry run" in preview and "journeys: 1" in preview and "artifacts: 1" in preview and "insights: 1" in preview
    assert not list(arcane.home.glob("index.db.bak-entity-org-*"))
    assert arcane.sql("SELECT org FROM artifacts WHERE id = 'unknown-artifact'") == [("",)]
    applied = _cli(arcane, *args, "--apply")
    assert "Assigned 3 entities" in applied
    [backup] = arcane.home.glob("index.db.bak-entity-org-*")
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT org FROM artifacts WHERE id = 'unknown-artifact'").fetchone() == ("",)
    conn.close()
    for table in ("journeys", "artifacts", "insights"):
        assert arcane.sql(f"SELECT COUNT(*) FROM {table} WHERE org = ''") == [(0,)]
    assert "No unknown-org entities" in _cli(arcane, *args, "--apply")
    shown = json.loads(_cli(arcane, "artifact", "show", "unknown-artifact"))
    assert shown["raw_data"] == {"body": "Recover content"}

    async def inspect(c: Client) -> Any:
        return await c.call("artifact_search", query="Recover content")

    assert [a["id"] for a in arcane.run(inspect)] == ["unknown-artifact"]
    # Duplicate external identities must refuse the whole batch, preserving
    # both records and leaving other unknown entities untouched.
    arcane.sql(
        "INSERT INTO artifacts (id,artifact_type,external_id,title,project,org,created_at) "
        "VALUES ('conflicting-unknown', 'commit', 'legacy-key', 'Duplicate', 'widget', '', '2026-01-01')"
    )
    arcane.sql(
        "INSERT INTO insights (id,insight_type,title,body,project,org,created_at) "
        "VALUES ('untouched-insight','health','Keep unknown','Body','widget','','2026-01-01')"
    )
    for suffix in ([], ["--apply"]):
        refused = subprocess.run(
            [ARCANE, *args, *suffix], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True
        )
        assert refused.returncode != 0 and "Ownership conflict" in refused.stderr
    assert len(list(arcane.home.glob("index.db.bak-entity-org-*"))) == 1
    assert arcane.sql("SELECT org FROM insights WHERE id = 'untouched-insight'") == [("",)]
    assert arcane.sql("SELECT COUNT(*) FROM artifacts WHERE external_id = 'legacy-key'") == [(2,)]


def test_derived_insights_and_context_do_not_include_foreign_org_data(arcane: Arcane, tmp_path: Path) -> None:
    beta = tmp_path / "other-org"
    git(tmp_path, "clone", "-q", str(arcane.repo), str(beta))
    git(beta, "remote", "set-url", "origin", "git@github.com:Beta/widget.git")

    async def foreign(c: Client) -> str:
        journey = await c.call("journey_start", title="Beta secret investigation")
        await c.call("memory_save", title="Beta secret memory", what="Private knowledge")
        await c.call("memory_search", query="Beta confidential query")
        await c.call("analyze", plugin_name="velocity")
        return journey["id"]

    beta_journey = arcane.run(foreign, cwd=beta)
    arcane.sql("UPDATE journeys SET updated_at = '2020-01-01' WHERE id = ?", (beta_journey,))

    async def own(c: Client) -> Any:
        await c.call("memory_save", title="Acme memory", what="Knowledge")
        await c.call("ingest_git")
        await c.call("memory_search", query="Acme absent question")
        for plugin in ("health", "velocity", "usage"):
            await c.call("analyze", plugin_name=plugin)
        return await c.call("memory_context")

    context = arcane.run(own)
    assert beta_journey not in {j["id"] for j in context.get("stale_journeys", [])}
    assert "stale_journeys" not in context
    assert all("Beta" not in i["title"] for i in context.get("insights", []))
    rows = arcane.sql("SELECT insight_type, title, body FROM insights WHERE org = 'acme'")
    assert all("Beta" not in body for _, _, body in rows)
    velocity = next(title for kind, title, _ in rows if kind == "velocity")
    assert velocity == "Velocity: 2 commits, 1 memories, 0 journeys"
    usage_bodies = [body for kind, _, body in rows if kind.startswith("usage")]
    assert any("Acme absent question" in body for body in usage_bodies)
    assert all("Beta confidential query" not in body and "Beta secret memory" not in body for body in usage_bodies)
