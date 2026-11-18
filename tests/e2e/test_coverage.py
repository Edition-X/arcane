"""E2E: ``arcane coverage`` over a real git history and memories saved through the real MCP server.

Provenance rules are proven the way they happen: the server runs inside the repo, on the PR
branch or at a commit, and stamps the commit and branch itself. The text and tag rules use
memories whose provenance is cleared, like the ones saved before provenance existed.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import ARCANE, Arcane, Client, git

_NO_SESSION = {"CLAUDE_CODE_SESSION_ID": "", "T3CODE_THREAD_ID": ""}


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"feat: {name}")
    return git(repo, "rev-parse", "HEAD").strip()


def _merge(repo: Path, number: int, branch: str, title: str) -> str:
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from Acme/{branch}", "-m", title, branch)
    return git(repo, "rev-parse", "HEAD").strip()


def _save(arcane: Arcane, title: str, **extra: Any) -> str:
    async def scenario(c: Client) -> Any:
        return await c.call("memory_save", title=title, what=extra.pop("what", f"What {title}"), **extra)

    return str(arcane.run(scenario, extra_env=_NO_SESSION)["id"])


def _forget_provenance(arcane: Arcane, memory_id: str) -> None:
    arcane.sql("UPDATE memories SET commit_sha = NULL, branch = NULL WHERE id = ?", (memory_id,))


def _coverage(arcane: Arcane, *args: str) -> dict[str, Any]:
    done = subprocess.run(
        [ARCANE, "coverage", "--json", *args], cwd=arcane.repo, env=arcane.env("full"), capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def _by_number(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {i["number"]: i for i in result["items"] if i["number"] is not None}


def _rules(item: dict[str, Any]) -> set[str]:
    return {m["rule"] for m in item["matched_by"]}


def test_provenance_rules_match_a_pr_by_commit_range_and_by_branch(arcane: Arcane) -> None:
    repo = arcane.repo
    # PR 11: memory saved at the first of two branch commits, on a detached HEAD, so only its SHA names the PR.
    git(repo, "checkout", "-q", "-b", "feat/by-range")
    first = _commit(repo, "range-a")
    _commit(repo, "range-b")
    git(repo, "checkout", "-q", "--detach", first)
    by_range = _save(arcane, "Saved inside the merged range")
    _merge(repo, 11, "feat/by-range", "Add range")

    # PR 12: memory saved on the branch, then the commit is amended, so its SHA is gone and only the branch matches.
    git(repo, "checkout", "-q", "-b", "feat/by-branch")
    _commit(repo, "branch-a")
    by_branch = _save(arcane, "Saved on the PR branch")
    git(repo, "commit", "-q", "--amend", "-m", "feat: branch-a, reworded")
    _merge(repo, 12, "feat/by-branch", "Add branch")

    # PR 13: nothing was saved for it.
    git(repo, "checkout", "-q", "-b", "feat/silent")
    _commit(repo, "silent")
    _merge(repo, 13, "feat/silent", "Add silence")

    assert arcane.sql("SELECT branch FROM memories WHERE id = ?", (by_range,)) == [(None,)]
    result = _coverage(arcane)
    prs = _by_number(result)
    assert prs[11]["subject"] == "Add range" and prs[11]["branch"] == "feat/by-range"
    assert prs[11]["matched_by"] == [{"rule": "commit_sha", "memory_id": by_range}]
    assert prs[12]["matched_by"] == [{"rule": "branch", "memory_id": by_branch}]
    assert not prs[13]["covered"] and prs[13]["matched_by"] == []


def test_direct_commits_are_covered_by_sha_only(arcane: Arcane) -> None:
    repo = arcane.repo
    covered = _commit(repo, "direct-covered")
    note = _save(arcane, "Saved at a direct commit")
    _commit(repo, "direct-bare")

    items = {i["sha"]: i for i in _coverage(arcane)["items"]}
    assert items[covered]["kind"] == "commit" and items[covered]["number"] is None
    assert items[covered]["matched_by"] == [{"rule": "commit_sha", "memory_id": note}]
    bare = [i for i in items.values() if i["subject"] == "feat: direct-bare"][0]
    assert not bare["covered"]


def test_tags_and_text_forms_name_a_pr_and_near_misses_do_not(arcane: Arcane) -> None:
    repo = arcane.repo
    forms = {
        31: {"tags": ["pr-31"]},
        32: {"tags": ["PR-32"]},
        33: {"tags": ["pr_33"]},
        34: {"what": "Shipped in PR #34"},
        35: {"what": "Shipped in PR 35"},
        36: {"title": "Fix from pr36"},
        37: {"what": "Shipped in #37"},
        38: {"what": "Discussed", "details": "Context.\n\nSee #38 for the rollout."},
        39: {"what": "Covers PRs #39 and #3900"},
        40: {"what": "Only a near miss: INF-#40, abc#40, #400, pr-400 and PR 4000"},
        41: {"what": "Only another project", "project": "toybox"},
    }
    for number in (3, *forms):
        git(repo, "checkout", "-q", "-b", f"feat/p{number}", "main")
        _commit(repo, f"p{number}")
        _merge(repo, number, f"feat/p{number}", f"Add {number}")
    ids: dict[int, str] = {}
    for number, extra in forms.items():
        if number == 40:
            continue
        ids[number] = _save(arcane, extra.pop("title", f"Memory for {number}"), **extra)
        _forget_provenance(arcane, ids[number])
    near_miss = _save(arcane, "Near misses", **forms[40])
    _forget_provenance(arcane, near_miss)

    prs = _by_number(_coverage(arcane))
    for number in range(31, 40):
        assert prs[number]["covered"], number
    assert _rules(prs[31]) == _rules(prs[32]) == _rules(prs[33]) == {"tag"}
    assert _rules(prs[34]) == _rules(prs[35]) == _rules(prs[36]) == _rules(prs[37]) == {"text"}
    assert prs[38]["matched_by"] == [{"rule": "text", "memory_id": ids[38]}]  # found in the details body
    assert prs[39]["matched_by"] == [{"rule": "text", "memory_id": ids[39]}]
    assert not prs[3]["covered"]  # "#39" and "#3900" are not PR 3
    assert not prs[40]["covered"]  # INF-#40, abc#40, #400, pr-400 and PR 4000 are not PR 40
    assert not prs[41]["covered"]  # another project's memory does not count


def test_a_memory_saved_at_the_merge_commit_covers_the_pr(arcane: Arcane) -> None:
    repo = arcane.repo
    git(repo, "checkout", "-q", "-b", "feat/merged")
    _commit(repo, "merged")
    merge = _merge(repo, 71, "feat/merged", "Add merged")
    note = _save(arcane, "Saved on main after the merge")

    pr = _by_number(_coverage(arcane))[71]
    assert pr["sha"] == merge
    assert pr["matched_by"] == [{"rule": "commit_sha", "memory_id": note}]


def test_a_squash_merge_is_a_pr_by_its_number(arcane: Arcane) -> None:
    repo = arcane.repo
    _commit(repo, "squashed")
    git(repo, "commit", "-q", "--amend", "-m", "feat: add squashing (#72)")
    squashed = git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, "squashed-bare")
    git(repo, "commit", "-q", "--amend", "-m", "feat: add bare squashing (#73)")
    note = _save(arcane, "Squash note", what="Shipped as PR #72")
    _forget_provenance(arcane, note)

    prs = _by_number(_coverage(arcane))
    assert prs[72]["kind"] == "pr" and prs[72]["sha"] == squashed and prs[72]["branch"] is None
    assert prs[72]["matched_by"] == [{"rule": "text", "memory_id": note}]
    assert not prs[73]["covered"]


def test_the_default_branch_name_never_matches_a_pr_head_branch(arcane: Arcane) -> None:
    repo = arcane.repo
    here = _save(arcane, "Saved on main")  # branch "main"
    git(repo, "checkout", "-q", "-b", "fork-main")
    _commit(repo, "from-a-fork")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #51 from someone/main", "-m", "Fork PR", "fork-main")
    assert here
    assert not _by_number(_coverage(arcane))[51]["covered"]


def test_text_summary_lists_uncovered_items_newest_first(arcane: Arcane) -> None:
    repo = arcane.repo
    git(repo, "checkout", "-q", "-b", "feat/seen")
    _commit(repo, "seen")
    _merge(repo, 61, "feat/seen", "Seen PR")
    seen = _save(arcane, "Seen", what="Done in PR #61")
    _forget_provenance(arcane, seen)
    git(repo, "checkout", "-q", "-b", "feat/unseen")
    _commit(repo, "unseen")
    _merge(repo, 62, "feat/unseen", "Unseen PR")
    sha = git(repo, "rev-parse", "--short=7", "HEAD").strip()

    done = arcane.cli("coverage")
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    assert lines[0].startswith("Coverage of acme/widget on main since ")
    assert re.search(r": 1/4 covered$", lines[0])
    assert lines[1] == "Matched by: commit_sha 0, branch 0, tag 0, text 1"
    uncovered = [line for line in lines if line.startswith("  ")]
    assert uncovered[0].split()[1:] == [sha, "#62", "Unseen", "PR"]
    assert uncovered[1].split()[2:] == ["feat:", "change", "two"]
    assert "#61" not in done.stdout.split("Uncovered")[1]


def test_window_keeps_commits_below_an_older_dated_one(
    arcane: Arcane, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-02T10:00:00+00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2020-01-02T10:00:00+00:00")
    old = _commit(arcane.repo, "ancient")
    monkeypatch.undo()
    _commit(arcane.repo, "recent")

    default = _coverage(arcane)
    shas = {item["sha"] for item in default["items"]}
    # The two setup commits sit below the 2020 one, and are still in the window.
    assert old not in shas and default["total"] == 3
    wide = _coverage(arcane, "--since", "2019-12-01")
    assert old in {item["sha"] for item in wide["items"]} and wide["total"] == 4
    assert _coverage(arcane, "--days", "36500")["total"] == 4
    assert "no commits" in arcane.cli("coverage", "--since", (date.today() + timedelta(days=2)).isoformat()).stdout


def test_days_counts_today_as_the_first_day(arcane: Arcane, monkeypatch: pytest.MonkeyPatch) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"{yesterday}T12:00:00+00:00")
    _commit(arcane.repo, "yesterday")
    monkeypatch.undo()
    today = _commit(arcane.repo, "today")

    one = {item["sha"] for item in _coverage(arcane, "--days", "1")["items"]}
    two = {item["sha"] for item in _coverage(arcane, "--days", "2")["items"]}
    assert today in one and len(one) == len(two) - 1


def test_default_branch_falls_back_to_origin_main_then_local_main(arcane: Arcane) -> None:
    repo = arcane.repo
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    behind = git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, "local-only")
    assert _coverage(arcane)["branch"] == "origin/main"
    assert behind in {item["sha"] for item in _coverage(arcane)["items"]}
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert _coverage(arcane)["branch"] == "main"


def test_edge_cases_exit_zero(arcane: Arcane, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    outside = subprocess.run([ARCANE, "coverage"], cwd=plain, env=arcane.env("full"), capture_output=True, text=True)
    assert outside.returncode == 0 and "not a git repository" in outside.stdout

    bad = arcane.cli("coverage", "--since", "yesterday", check=False)
    assert bad.returncode == 2 and "YYYY-MM-DD" in bad.stderr


def test_a_failing_git_log_is_an_error_not_an_empty_window(arcane: Arcane) -> None:
    repo = arcane.repo
    root = git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    (repo / ".git" / "objects" / root[:2] / root[2:]).unlink()

    result = _coverage(arcane)
    assert result == {"error": "git log failed on main"}
    assert "no commits" not in arcane.cli("coverage").stdout
