"""Coverage: which merged PRs and direct commits have a memory behind them.

``build_coverage`` walks the default branch's first-parent history and checks each
merge commit (a PR) or direct commit against the current project's memories. A
memory covers an item through any of four rules: its provenance ``commit_sha`` is
the commit or inside the merged branch, its provenance ``branch`` is the PR's head
branch, a ``pr-N`` style tag names the PR, or its text says "PR N", "PR #N" or "#N".
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from datetime import date
from typing import Any

from arcane.domain.scope import resolve_scope
from arcane.services.container import ServiceContainer

RULES = ("commit_sha", "branch", "tag", "text")
TEXT_FIELDS = ("title", "what", "why", "impact", "details")

_MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+) from (\S+)")
_SQUASH_SUBJECT = re.compile(r"\(#(\d+)\)$")
_PR_TAG = re.compile(r"^pr[-_ ]?(\d+)$", re.IGNORECASE)
# "PR 12", "PR #12", "PRs #12", "pr12", "PR-12". A letter or digit before "pr" means a word, not a PR.
_PR_TEXT = re.compile(r"(?<![A-Za-z0-9])prs?[-_ ]?#?(\d+)(?!\d)", re.IGNORECASE)
# GitHub numbers issues and PRs together and Linear keys are "INF-12", so a bare "#12" names this
# repo's PR 12 unless a letter, digit or "-" sits before it ("abc#12", "INF-#12").
_BARE_NUMBER = re.compile(r"(?<![A-Za-z0-9-])#(\d+)(?!\d)")

_FIELD_SEP, _RECORD_SEP = "\x1f", "\x1e"
_GIT_TIMEOUT_S = 60
SHORT_SHA_LEN = 7


def _git(cwd: str, *args: str) -> str | None:
    """Stdout of ``git -C cwd <args>``, or None when git fails, times out or is missing.

    Empty stdout is a real answer (``rev-list`` of an empty range), so it comes back as "".
    ``--no-optional-locks`` keeps a read from taking ``index.lock`` under the agent's own git.
    """
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch(cwd: str) -> str | None:
    """The default branch: ``origin/HEAD``, else ``origin/main``, ``origin/master``, local ``main``,
    ``master``, and last ``HEAD``. None when the directory has no commits."""
    remote_head = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote_head and remote_head.strip():
        return remote_head.strip()
    for name, ref in (
        ("origin/main", "refs/remotes/origin/main"),
        ("origin/master", "refs/remotes/origin/master"),
        ("main", "refs/heads/main"),
        ("master", "refs/heads/master"),
    ):
        if _git(cwd, "rev-parse", "--verify", "--quiet", ref) is not None:
            return name
    return "HEAD" if _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD") is not None else None


def walk_history(cwd: str, branch: str, since: date) -> list[tuple[dict[str, Any], list[str]]] | None:
    """First-parent commits of *branch* committed on or after *since*, newest first, as ``(item, shas)``.

    *shas* are the commits the item stands for: the commit, plus for a PR merge everything it merged.
    None when ``git log`` fails. The window is filtered here, not with ``git log --since``, because
    git stops at the first older-dated commit and drops in-window commits below it.

    A two-parent commit titled "Merge pull request #N from owner/head" is a PR with its head
    branch. A one-parent commit ending in "(#N)" is a squash-merged PR. Anything else, including
    a plain ``git merge``, is a direct commit. A head branch name that was used for two PRs is
    the same name to the branch rule, so a memory saved on it matches both.
    """
    fmt = _FIELD_SEP.join(["%H", "%P", "%cs", "%s", "%b"]) + _RECORD_SEP
    out = _git(cwd, "log", "--first-parent", f"--format={fmt}", branch)
    if out is None:
        return None
    walked: list[tuple[dict[str, Any], list[str]]] = []
    for record in out.split(_RECORD_SEP):
        if not record.strip():
            continue
        sha, parents, day, subject, body = record.strip("\n").split(_FIELD_SEP)
        if day < since.isoformat():
            continue
        shas = [sha]
        item: dict[str, Any] = {
            "kind": "commit",
            "sha": sha,
            "number": None,
            "branch": None,
            "date": day,
            "subject": subject,
        }
        merge = _MERGE_SUBJECT.match(subject)
        squash = _SQUASH_SUBJECT.search(subject)
        if merge and len(parents.split()) == 2:
            item.update(kind="pr", number=int(merge.group(1)), branch=merge.group(2).partition("/")[2] or None)
            # GitHub puts the PR title on the first body line; the subject only says "Merge pull request".
            title = next((line for line in body.splitlines() if line.strip()), subject)
            item["subject"] = title.strip()
            merged = _git(cwd, "rev-list", f"{sha}^1..{sha}^2")
            shas += (merged or "").split()
        elif squash and len(parents.split()) == 1:
            item.update(kind="pr", number=int(squash.group(1)))
        walked.append((item, shas))
    return walked


def _index_memories(memories: list[dict[str, Any]]) -> dict[str, dict[Any, list[str]]]:
    """Map each rule's key (a SHA, a branch name or a PR number) to the memories that carry it."""
    index: dict[str, dict[Any, list[str]]] = {rule: defaultdict(list) for rule in RULES}
    for memory in memories:
        memory_id = memory["id"]
        if memory.get("commit_sha"):
            index["commit_sha"][memory["commit_sha"]].append(memory_id)
        if memory.get("branch"):
            index["branch"][memory["branch"]].append(memory_id)
        for tag in memory.get("tags") or []:
            tagged = _PR_TAG.match(tag.strip())
            if tagged:
                index["tag"][int(tagged.group(1))].append(memory_id)
        numbers: set[int] = set()
        for field in TEXT_FIELDS:
            text = memory.get(field) or ""
            numbers.update(int(n) for pattern in (_PR_TEXT, _BARE_NUMBER) for n in pattern.findall(text))
        for number in numbers:
            index["text"][number].append(memory_id)
    return index


def _matches(
    item: dict[str, Any], shas: list[str], index: dict[str, dict[Any, list[str]]], default_branch_ref: str
) -> list[dict[str, str]]:
    """The memories that cover *item*, each as ``{"rule", "memory_id"}``.

    *shas* are the commits the item stands for. The branch rule compares names only, so a head
    branch name reused by two PRs matches a memory saved on either; the default branch's own name
    never matches, since a fork's PR from its ``main`` would otherwise take every memory saved there.
    """
    found: list[dict[str, str]] = []

    def add(rule: str, memory_ids: list[str]) -> None:
        found.extend({"rule": rule, "memory_id": memory_id} for memory_id in dict.fromkeys(memory_ids))

    for sha in shas:
        add("commit_sha", index["commit_sha"].get(sha, []))
    if item["branch"] and item["branch"] != default_branch_ref.removeprefix("origin/"):
        add("branch", index["branch"].get(item["branch"], []))
    if item["number"] is not None:
        add("tag", index["tag"].get(item["number"], []))
        add("text", index["text"].get(item["number"], []))
    return found


def build_coverage(container: ServiceContainer, cwd: str, since: date) -> dict[str, Any]:
    """Classify the default branch's history since *since* against the current project's memories.

    Returns ``{"error": ...}`` outside a git repository, without any commit, or when ``git log`` fails.
    """
    branch = default_branch(cwd)
    if branch is None:
        return {"error": "not a git repository with commits"}
    walked = walk_history(cwd, branch, since)
    if walked is None:
        return {"error": f"git log failed on {branch}"}
    scope = resolve_scope(cwd, container.config)
    index = _index_memories(container.memory_repo.list_for_export(scope.org, scope.project))

    items = []
    for item, shas in walked:
        matched_by = _matches(item, shas, index, branch)
        items.append({**item, "matched_by": matched_by, "covered": bool(matched_by)})
    by_rule = {
        rule: sum(any(match["rule"] == rule for match in entry["matched_by"]) for entry in items) for rule in RULES
    }
    return {
        "org": scope.org,
        "project": scope.project,
        "branch": branch,
        "since": since.isoformat(),
        "covered": sum(entry["covered"] for entry in items),
        "total": len(items),
        "by_rule": by_rule,
        "items": items,
    }


def render_text(result: dict[str, Any]) -> str:
    """The summary line, rule counts and the uncovered items, one per line."""
    if "error" in result:
        return f"Coverage: {result['error']}."
    head = f"Coverage of {result['org']}/{result['project']} on {result['branch']} since {result['since']}"
    if not result["total"]:
        return f"{head}: no commits."
    lines = [f"{head}: {result['covered']}/{result['total']} covered"]
    lines.append("Matched by: " + ", ".join(f"{rule} {n}" for rule, n in result["by_rule"].items()))
    uncovered = [entry for entry in result["items"] if not entry["covered"]]
    if uncovered:
        lines += ["", f"Uncovered ({len(uncovered)}):"]
        for entry in uncovered:
            label = f"#{entry['number']} " if entry["number"] is not None else ""
            lines.append(f"  {entry['date']}  {entry['sha'][:SHORT_SHA_LEN]}  {label}{entry['subject']}")
    return "\n".join(lines)
