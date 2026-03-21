"""CI flake detection intelligence plugin.

Analyzes CI run artifacts to detect flaky tests/builds — cases where the same
commit fails then succeeds on retry.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from arcane.infra.db.artifact_repo import ArtifactRepository


class CIFlakeDetector:
    name = "ci_flakes"

    def __init__(self, artifact_repo: ArtifactRepository | None = None) -> None:
        self.artifact_repo = artifact_repo

    def analyze(self, project: str) -> list[dict[str, Any]]:
        if not self.artifact_repo:
            return []

        runs = self.artifact_repo.list_all(project=project, artifact_type="ci_run", limit=500)
        if not runs:
            return []

        # Group runs by commit SHA
        by_sha: dict[str, list[dict]] = defaultdict(list)
        for run in runs:
            raw = run.get("raw_data")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not raw:
                continue
            sha = raw.get("head_sha")
            if sha:
                by_sha[sha].append({"run": run, "raw": raw})

        # Detect flakes: same commit has both failure and success
        flaky_commits: list[dict[str, Any]] = []
        for sha, sha_runs in by_sha.items():
            conclusions = {r["raw"].get("conclusion") for r in sha_runs}
            if "failure" in conclusions and "success" in conclusions:
                flaky_commits.append({
                    "sha": sha,
                    "runs": sha_runs,
                    "branch": sha_runs[0]["raw"].get("head_branch", "unknown"),
                })

        if not flaky_commits:
            return []

        # Build a summary insight
        now = datetime.now(timezone.utc).isoformat()
        branches = list({fc["branch"] for fc in flaky_commits})
        shas = [fc["sha"][:8] for fc in flaky_commits]

        body_lines = [
            f"Detected {len(flaky_commits)} flaky commit(s) in project '{project}'.",
            "",
            "Flaky commits (failed then succeeded on retry):",
        ]
        for fc in flaky_commits:
            body_lines.append(f"  - {fc['sha'][:8]} on {fc['branch']} ({len(fc['runs'])} runs)")

        return [{
            "id": str(uuid.uuid4()),
            "insight_type": "ci_flake",
            "title": f"CI flakes detected: {len(flaky_commits)} flaky commit(s)",
            "body": "\n".join(body_lines),
            "severity": "warning" if len(flaky_commits) >= 3 else "info",
            "project": project,
            "metadata": {
                "flake_count": len(flaky_commits),
                "flaky_shas": shas,
                "branches": branches,
            },
            "created_at": now,
        }]
