"""E2E: ``arcane report`` and ``arcane export`` over a store filled through the MCP server."""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client


def _cli(arcane: Arcane, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ARCANE, *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True, check=check
    )


def _fill(arcane: Arcane) -> dict[str, Any]:
    async def scenario(c: Client) -> dict[str, Any]:
        journey = await c.call("journey_start", title="Runner flakes")
        shipped = await c.call(
            "memory_save", title="Runner image pinned", what="Pinned the runner image to a digest",
            category="milestone", journey_id=journey["id"],
        )  # fmt: skip
        decided = await c.call(
            "memory_save", title="Pin images by digest", what="Use digests, not tags",
            why="Tags moved under us twice", category="decision", details="Considered: tags, digests",
        )  # fmt: skip
        await c.call("memory_save", title="Disk filled by images", what="Docker never pruned", category="bug")
        await c.call("memory_save", title="Just context", what="Not in a report", category="context")
        await c.call(
            "memory_save", title="Side project shipped", what="Personal thing", category="milestone",
            project="toybox", org="personal",
        )  # fmt: skip
        old = await c.call("memory_save", title="Old decision", what="Long ago", category="decision")
        await c.call("journey_complete", journey_id=journey["id"], summary="Pinned and pruned")
        await c.call("ingest_git", max_count=10)
        return {"journey": journey["id"], "shipped": shipped["id"], "decided": decided["id"], "old": old["id"]}

    ids = arcane.run(scenario)
    arcane.sql("UPDATE memories SET created_at = '2025-01-15T10:00:00+00:00' WHERE id = ?", (ids["old"],))
    return ids


def test_report_groups_work_by_org_and_project(arcane: Arcane) -> None:
    _fill(arcane)
    today = date.today()

    out = _cli(arcane, "report", "--days", "1").stdout
    assert out.startswith(f"# Work report: {today} to {today}\n")
    assert "2 shipped · 1 decisions · 1 bugs fixed · 1 investigations finished" in out
    assert "## acme\n\n### widget" in out and "## personal\n\n### toybox" in out
    assert f"- {today} **Pin images by digest** — Tags moved under us twice" in out  # decisions show why
    assert f"- {today} **Runner image pinned** — Pinned the runner image to a digest" in out
    assert "**Investigations finished**" in out and "**Runner flakes** — Pinned and pruned" in out
    assert "Just context" not in out and "Old decision" not in out

    acme = _cli(arcane, "report", "--days", "1", "--org", "Acme").stdout
    assert "toybox" not in acme and "(acme)" in acme.splitlines()[0]

    old = _cli(arcane, "report", "--since", "2025-01-01", "--until", "2025-01-31").stdout
    assert "0 shipped · 1 decisions · 0 bugs fixed · 0 investigations finished" in old
    assert "**Old decision**" in old

    empty = _cli(arcane, "report", "--days", "1", "--project", "nothing-here").stdout
    assert "Nothing recorded in this period." in empty


def test_report_json_for_skills(arcane: Arcane) -> None:
    ids = _fill(arcane)
    data = json.loads(_cli(arcane, "report", "--days", "2", "--project", "widget", "--format", "json").stdout)
    assert data["since"] == (date.today() - timedelta(days=1)).isoformat()
    assert data["totals"] == {"milestone": 1, "decision": 1, "bug": 1, "journey": 1}
    [group] = data["projects"]
    assert (group["org"], group["project"]) == ("acme", "widget")
    kinds = {e["id"]: e["kind"] for e in group["entries"]}
    assert kinds[ids["decided"]] == "decision" and kinds[ids["journey"]] == "journey"


def test_report_rejects_bad_dates(arcane: Arcane) -> None:
    bad = _cli(arcane, "report", "--since", "24/10/2026", check=False)
    assert bad.returncode != 0 and "use YYYY-MM-DD" in bad.stderr
    backwards = _cli(arcane, "report", "--since", "2026-02-01", "--until", "2026-01-01", check=False)
    assert backwards.returncode != 0 and "must not be after --until" in backwards.stderr


def test_export_holds_everything_one_org_owns(arcane: Arcane, tmp_path: Path) -> None:
    ids = _fill(arcane)
    out = tmp_path / "acme.json"

    message = _cli(arcane, "export", "--org", "acme", "--out", str(out)).stdout
    assert "Exported 5 memories, 1 journeys, 2 artifacts and 1 links from 1 projects" in message

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["format"] == "arcane-export" and data["version"] == 1 and data["org"] == "acme"
    assert data["projects"] == ["widget"]
    memories = {m["id"]: m for m in data["memories"]}
    assert "Side project shipped" not in {m["title"] for m in data["memories"]}
    assert memories[ids["decided"]]["details"] == "Considered: tags, digests"
    assert memories[ids["decided"]]["tags"] == []
    [journey] = data["journeys"]
    assert journey["status"] == "completed" and [e["event_type"] for e in journey["events"]] == ["completed"]
    assert {a["title"] for a in data["artifacts"]} == {"feat: change 1", "feat: change 2"}
    assert all(isinstance(a["raw_data"], dict) for a in data["artifacts"])
    assert (ids["shipped"], ids["journey"]) in {(r["source_id"], r["target_id"]) for r in data["relationships"]}
    assert all("rowid" not in record for record in (*data["memories"], *data["journeys"], *data["artifacts"]))


def test_export_of_an_unknown_org_fails_without_writing(arcane: Arcane, tmp_path: Path) -> None:
    _fill(arcane)
    out = tmp_path / "none.json"
    result = _cli(arcane, "export", "--org", "nobody", "--out", str(out), check=False)
    assert result.returncode != 0 and "No memories in org 'nobody'" in result.stderr
    assert not out.exists()
