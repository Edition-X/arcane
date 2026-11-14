"""E2E: every save records the commit, branch and session it came from."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tests.e2e.conftest import ARCANE, Arcane, Client, git

_COLUMNS = "commit_sha, branch, dirty, session_id, thread_id, harness"
# The suite may itself run inside an agent; start every server from a clean slate.
_NO_SESSION = {"CLAUDE_CODE_SESSION_ID": "", "T3CODE_THREAD_ID": "", "CLAUDECODE": ""}


def _save(c: Client, title: str) -> Any:
    return c.call("memory_save", title=title, what=f"What {title}")


def test_save_records_commit_branch_and_clean_tree(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()

    async def scenario(c: Client) -> Any:
        return await _save(c, "Records the commit")

    saved = arcane.run(scenario, client_name="Claude Code", extra_env=_NO_SESSION)
    row = arcane.sql(f"SELECT {_COLUMNS} FROM memories WHERE id = ?", (saved["id"],))[0]
    assert row == (head, "main", 0, None, None, "claude-code")


def test_dirty_tree_and_detached_head(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    (arcane.repo / "file-one.txt").write_text("edited\n", encoding="utf-8")

    async def scenario(c: Client) -> Any:
        return await _save(c, "Dirty tree")

    dirty = arcane.run(scenario, extra_env=_NO_SESSION)
    git(arcane.repo, "checkout", "-q", "--detach")
    detached = arcane.run(lambda c: _save(c, "Detached head"), extra_env=_NO_SESSION)

    rows = {
        mid: arcane.sql("SELECT commit_sha, branch, dirty FROM memories WHERE id = ?", (mid,))[0]
        for mid in (dirty["id"], detached["id"])
    }
    assert rows[dirty["id"]] == (head, "main", 1)
    assert rows[detached["id"]] == (head, None, 1)


def test_save_outside_a_git_repo_has_empty_fields(arcane: Arcane, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    async def scenario(c: Client) -> Any:
        return await c.call("memory_save", title="No repo", what="Saved from a plain folder", project="notes")

    saved = arcane.run(scenario, cwd=plain, client_name="Claude Code", extra_env=_NO_SESSION)
    row = arcane.sql(f"SELECT {_COLUMNS} FROM memories WHERE id = ?", (saved["id"],))[0]
    assert row == (None, None, None, None, None, "claude-code")


def test_session_and_thread_ids_from_the_environment(arcane: Arcane) -> None:
    env = {"CLAUDE_CODE_SESSION_ID": "sess-env-1", "T3CODE_THREAD_ID": "thread-env-1", "CLAUDECODE": ""}

    async def scenario(c: Client) -> Any:
        return await _save(c, "Ids from env")

    saved = arcane.run(scenario, client_name="Claude Code", extra_env=env)
    row = arcane.sql("SELECT session_id, thread_id, harness FROM memories WHERE id = ?", (saved["id"],))[0]
    assert row == ("sess-env-1", "thread-env-1", "claude-code")


def test_memory_details_returns_the_provenance(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    env = {**_NO_SESSION, "CLAUDE_CODE_SESSION_ID": "sess-details"}

    async def scenario(c: Client) -> Any:
        saved = await c.call("memory_save", title="Shown in details", what="What", details="Body text")
        return await c.call("memory_details", memory_id=saved["id"][:8])

    details = arcane.run(scenario, client_name="Claude Code", extra_env=env)
    assert details["body"] == "Body text"
    assert details["provenance"] == {
        "commit_sha": head,
        "branch": "main",
        "dirty": False,
        "session_id": "sess-details",
        "thread_id": None,
        "harness": "claude-code",
    }


def test_agent_cannot_supply_the_caller(arcane: Arcane) -> None:
    async def scenario(c: Client) -> Any:
        saved = await c.call(
            "memory_save",
            title="Spoof attempt",
            what="What",
            caller={"client": "spoof", "meta": {"sessionId": "forged"}},
        )
        return saved

    saved = arcane.run(scenario, client_name="Claude Code", extra_env=_NO_SESSION)
    row = arcane.sql("SELECT session_id, harness FROM memories WHERE id = ?", (saved["id"],))[0]
    assert row == (None, "claude-code")


def test_cli_save_records_the_same(arcane: Arcane) -> None:
    head = git(arcane.repo, "rev-parse", "HEAD").strip()
    env = {**arcane.env("full"), "CLAUDE_CODE_SESSION_ID": "sess-cli", "T3CODE_THREAD_ID": "", "CLAUDECODE": ""}
    subprocess.run(
        [ARCANE, "save", "--title", "Saved by CLI", "--what", "What"],
        cwd=arcane.repo,
        env=env,
        check=True,
        capture_output=True,
    )
    row = arcane.sql(f"SELECT {_COLUMNS} FROM memories WHERE title = 'Saved by CLI'")[0]
    assert row == (head, "main", 0, "sess-cli", None, None)


def test_call_meta_wins_over_the_start_up_environment(arcane: Arcane) -> None:
    """Codex sends sessionId and threadId on every call; they are current, the environment is not."""
    env = {"CLAUDE_CODE_SESSION_ID": "sess-stale", "T3CODE_THREAD_ID": "thread-stale", "CLAUDECODE": ""}

    async def scenario(c: Client) -> Any:
        result = await c.session.call_tool(
            "memory_save",
            {"title": "Ids from meta", "what": "What"},
            meta={"sessionId": "sess-meta", "threadId": "thread-meta"},
        )
        return result.content[0].text  # type: ignore[union-attr]

    arcane.run(scenario, client_name="codex-mcp-client", extra_env=env)
    row = arcane.sql("SELECT session_id, thread_id, harness FROM memories WHERE title = 'Ids from meta'")[0]
    assert row == ("sess-meta", "thread-meta", "codex")
