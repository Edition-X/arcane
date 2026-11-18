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


def _git(cwd: str, *args: str) -> str | None:
    """Stdout of ``git -C cwd <args>``, or None when git fails or is missing."""
    try:
        done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch(cwd: str) -> str | None:
    """The default branch: ``origin/HEAD``, else a local ``main`` or ``master``, else ``HEAD``."""
    remote_head = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote_head and remote_head.strip():
        return remote_head.strip()
    for name in ("main", "master"):
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return "HEAD" if _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD") is not None else None


def walk_history(cwd: str, branch: str, since: date) -> list[dict[str, Any]]:
    """First-parent commits of *branch* since *since*, newest first, each classified as a PR or a commit.

    A two-parent commit titled "Merge pull request #N from owner/head" is a PR with its head
    branch and the commits it merged. A one-parent commit ending in "(#N)" is a squash-merged PR.
    Anything else, including a plain ``git merge``, is a direct commit.
    """
    fmt = _FIELD_SEP.join(["%H", "%P", "%cs", "%s", "%b"]) + _RECORD_SEP
    out = _git(cwd, "log", "--first-parent", f"--since={since.isoformat()}T00:00:00", f"--format={fmt}", branch)
    items: list[dict[str, Any]] = []
    for record in (out or "").split(_RECORD_SEP):
        if not record.strip():
            continue
        sha, parents, day, subject, body = record.strip("\n").split(_FIELD_SEP)
        shas = [sha]
        item: dict[str, Any] = {"kind": "commit", "number": None, "branch": None, "date": day, "subject": subject}
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
        item.update(sha=sha, shas=shas)
        items.append(item)
    return items


def _index_memories(memories: list[dict[str, Any]]) -> dict[str, dict[Any, list[str]]]:
    """Map each rule's key (a SHA, a branch name or a PR number) to the memories that carry it."""
    index: dict[str, dict[Any, list[str]]] = {rule: defaultdict(list) for rule in RULES}
    for m in memories:
        mid = m["id"]
        if m.get("commit_sha"):
            index["commit_sha"][m["commit_sha"]].append(mid)
        if m.get("branch"):
            index["branch"][m["branch"]].append(mid)
        for tag in m.get("tags") or []:
            tagged = _PR_TAG.match(tag.strip())
            if tagged:
                index["tag"][int(tagged.group(1))].append(mid)
        numbers: set[int] = set()
        for field in TEXT_FIELDS:
            text = m.get(field) or ""
            numbers.update(int(n) for pattern in (_PR_TEXT, _BARE_NUMBER) for n in pattern.findall(text))
        for number in numbers:
            index["text"][number].append(mid)
    return index


def _matches(item: dict[str, Any], index: dict[str, dict[Any, list[str]]], default: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def add(rule: str, ids: list[str]) -> None:
        found.extend({"rule": rule, "memory_id": mid} for mid in dict.fromkeys(ids))

    for sha in item["shas"]:
        add("commit_sha", index["commit_sha"].get(sha, []))
    # A fork's "main" would match every memory saved on the default branch.
    if item["branch"] and item["branch"] != default.removeprefix("origin/"):
        add("branch", index["branch"].get(item["branch"], []))
    if item["number"] is not None:
        add("tag", index["tag"].get(item["number"], []))
        add("text", index["text"].get(item["number"], []))
    return found


def build_coverage(container: ServiceContainer, cwd: str, since: date) -> dict[str, Any]:
    """Classify the default branch's history since *since* against the current project's memories.

    Returns ``{"error": ...}`` outside a git repository or without any commit.
    """
    branch = default_branch(cwd)
    if branch is None:
        return {"error": "not a git repository with commits"}
    scope = resolve_scope(cwd, container.config)
    index = _index_memories(container.memory_repo.list_for_project(scope.org, scope.project))

    items = walk_history(cwd, branch, since)
    for item in items:
        item["matched_by"] = _matches(item, index, branch)
        item["covered"] = bool(item["matched_by"])
        del item["shas"]
    by_rule = {rule: sum(any(m["rule"] == rule for m in i["matched_by"]) for i in items) for rule in RULES}
    return {
        "org": scope.org,
        "project": scope.project,
        "branch": branch,
        "since": since.isoformat(),
        "covered": sum(i["covered"] for i in items),
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
    uncovered = [i for i in result["items"] if not i["covered"]]
    if uncovered:
        lines += ["", f"Uncovered ({len(uncovered)}):"]
        for i in uncovered:
            label = f"#{i['number']} " if i["number"] is not None else ""
            lines.append(f"  {i['date']}  {i['sha'][:7]}  {label}{i['subject']}")
    return "\n".join(lines)
