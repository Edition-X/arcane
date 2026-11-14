"""E2E: every save records the commit, branch and session it came from."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client, git

_COLUMNS = "commit_sha, branch, dirty, session_id, thread_id"
# The suite may itself run inside an agent; start every server from a clean slate.
_NO_SESSION = {"CLAUDE_CODE_SESSION_ID": "", "T3CODE_THREAD_ID": ""}


def _save(c: Client, title: str, **extra: Any) -> Any:
    return c.call("memory_save", title=title, what=f"What {title}", **extra)


def _row(arcane: Arcane, memory_id: str) -> tuple[Any, ...]:
    return arcane.sql(f"SELECT {_COLUMNS} FROM memories WHERE id = ?", (memory_id,))[0]


def test_save_records_commit_branch_and_clean_tree(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    saved = arcane.run(lambda c: _save(c, "Records the commit"), extra_env=_NO_SESSION)
    assert _row(arcane, saved["id"]) == (head, "main", 0, None, None)


def test_dirty_tree_and_detached_head(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    (arcane.repo / "file-one.txt").write_text("edited\n", encoding="utf-8")
    dirty = arcane.run(lambda c: _save(c, "Dirty tree"), extra_env=_NO_SESSION)
    git(arcane.repo, "checkout", "-q", "--detach")
    detached = arcane.run(lambda c: _save(c, "Detached head"), extra_env=_NO_SESSION)
    assert _row(arcane, dirty["id"])[:3] == (head, "main", 1)
    assert _row(arcane, detached["id"])[:3] == (head, None, 1)


def test_save_outside_a_git_repo_has_empty_fields(arcane: Arcane, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    saved = arcane.run(lambda c: _save(c, "No repo", project="notes"), cwd=plain, extra_env=_NO_SESSION)
    assert _row(arcane, saved["id"]) == (None, None, None, None, None)


def test_session_and_thread_ids_from_the_environment(arcane: Arcane) -> None:
    env = {"CLAUDE_CODE_SESSION_ID": "sess-env-1", "T3CODE_THREAD_ID": "thread-env-1"}
    saved = arcane.run(lambda c: _save(c, "Ids from env"), extra_env=env)
    assert _row(arcane, saved["id"])[3:] == ("sess-env-1", "thread-env-1")


def test_session_from_call_meta_wins_but_the_t3_thread_does_too(arcane: Arcane) -> None:
    """Codex sends sessionId and threadId on every call. The session is current there; the T3 thread is openable."""
    env = {"CLAUDE_CODE_SESSION_ID": "sess-stale", "T3CODE_THREAD_ID": "thread-t3"}

    async def scenario(c: Client) -> Any:
        result = await c.session.call_tool(
            "memory_save",
            {"title": "Ids from meta", "what": "What"},
            meta={"sessionId": "sess-meta", "threadId": "thread-meta"},
        )
        assert result.is_error is False
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    saved = arcane.run(scenario, client_name="codex-mcp-client", extra_env=env)
    assert _row(arcane, saved["id"])[3:] == ("sess-meta", "thread-t3")

    async def meta_only(c: Client) -> Any:
        result = await c.session.call_tool(
            "memory_save", {"title": "Thread from meta", "what": "What"}, meta={"threadId": "thread-meta"}
        )
        assert result.is_error is False
        return json.loads(result.content[0].text)  # type: ignore[union-attr]

    saved = arcane.run(meta_only, client_name="codex-mcp-client", extra_env=_NO_SESSION)
    assert _row(arcane, saved["id"])[3:] == (None, "thread-meta")


def test_memory_details_returns_the_provenance(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    env = {**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": "sess-details"}

    async def scenario(c: Client) -> Any:
        saved = await c.call("memory_save", title="Shown in details", what="What", details="Body text")
        return await c.call("memory_details", memory_id=saved["id"][:8])

    details = arcane.run(scenario, extra_env=env)
    assert details["provenance"] == {
        "commit_sha": head,
        "branch": "main",
        "dirty": False,
        "session_id": "sess-details",
        "thread_id": None,
    }


def test_agent_cannot_supply_the_caller(arcane: Arcane) -> None:
    saved = arcane.run(
        lambda c: _save(c, "Spoof attempt", caller={"meta": {"sessionId": "forged"}}), extra_env=_NO_SESSION
    )
    assert _row(arcane, saved["id"])[3] is None


def test_resave_of_the_same_title_replaces_the_provenance(arcane: Arcane) -> None:
    first_head = git(arcane.repo, "rev-parse", "HEAD").strip()
    first = arcane.run(
        lambda c: _save(c, "Saved twice"), extra_env={**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": "sess-first"}
    )
    (arcane.repo / "file-three.txt").write_text("three\n", encoding="utf-8")
    git(arcane.repo, "add", ".")
    git(arcane.repo, "commit", "-q", "-m", "feat: change three")
    second_head = git(arcane.repo, "rev-parse", "HEAD").strip()
    assert second_head != first_head

    second = arcane.run(
        lambda c: _save(c, "Saved twice", why="Changed my mind"),
        extra_env={**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": "sess-second"},
    )
    assert second["id"] == first["id"] and second["action"] == "updated"
    assert _row(arcane, first["id"]) == (second_head, "main", 0, "sess-second", None)


def test_explicit_other_project_keeps_the_session_but_not_this_checkouts_commit(arcane: Arcane) -> None:
    env = {**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": "sess-other"}
    other = arcane.run(lambda c: _save(c, "About another repo", project="gadget"), extra_env=env)
    own = arcane.run(lambda c: _save(c, "About this repo", project="widget"), extra_env=env)
    org_wide = arcane.run(lambda c: _save(c, "About the org", scope="org"), extra_env=env)
    head = git(arcane.repo, "rev-parse", "HEAD").strip()

    assert _row(arcane, other["id"]) == (None, None, None, "sess-other", None)
    assert _row(arcane, own["id"]) == (head, "main", 0, "sess-other", None)
    assert _row(arcane, org_wide["id"]) == (None, None, None, "sess-other", None)


def test_cli_save_records_the_same(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    env = {**arcane.env("full"), "CLAUDE_CODE_SESSION_ID": "sess-cli", "T3CODE_THREAD_ID": ""}
    subprocess.run(
        [ARCANE, "save", "--title", "Saved by CLI", "--what", "What"],
        cwd=arcane.repo,
        env=env,
        check=True,
        capture_output=True,
    )
    row = arcane.sql(f"SELECT {_COLUMNS} FROM memories WHERE title = 'Saved by CLI'")[0]
    assert row == (head, "main", 0, "sess-cli", None)


def test_export_carries_the_provenance(arcane: Arcane, tmp_path: Path) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    arcane.run(lambda c: _save(c, "Exported", details="d"), extra_env={**_NO_SESSION, "T3CODE_THREAD_ID": "thr-x"})
    out = tmp_path / "export.json"
    subprocess.run(
        [ARCANE, "export", "--org", "acme", "--out", str(out)],
        cwd=arcane.repo,
        env=arcane.env("full"),
        check=True,
        capture_output=True,
    )
    memory = json.loads(out.read_text(encoding="utf-8"))["memories"][0]
    assert (memory["commit_sha"], memory["branch"], memory["dirty"], memory["thread_id"]) == (head, "main", 0, "thr-x")


def test_store_from_before_the_columns_upgrades_and_keeps_its_rows(arcane: Arcane) -> None:
    old = arcane.run(lambda c: _save(c, "Saved before the upgrade"), extra_env=_NO_SESSION)
    arcane.sql("DROP INDEX idx_memories_commit")
    for column in ("commit_sha", "branch", "dirty", "session_id", "thread_id"):
        arcane.sql(f"ALTER TABLE memories DROP COLUMN {column}")
    before = arcane.sql("SELECT id, title FROM memories")
    head = git(arcane.repo, "rev-parse", "HEAD").strip()

    for n in (1, 2):  # the second start finds the columns already there
        env = {**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": f"sess-up-{n}"}
        saved = arcane.run(lambda c, n=n: _save(c, f"Saved after the upgrade {n}"), extra_env=env)
        assert _row(arcane, saved["id"]) == (head, "main", 0, f"sess-up-{n}", None)

    assert _row(arcane, old["id"]) == (None, None, None, None, None)
    assert set(before) <= set(arcane.sql("SELECT id, title FROM memories"))
    assert arcane.sql("SELECT name FROM sqlite_master WHERE name = 'idx_memories_commit'") == [("idx_memories_commit",)]
