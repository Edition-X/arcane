"""Read-only git calls for the services that look at a repository's history."""

from __future__ import annotations

import subprocess

GIT_TIMEOUT_S = 60


def git_output(cwd: str, *args: str) -> str | None:
    """Stdout of ``git -C cwd <args>``, or None when git fails, times out or is missing.

    Empty stdout is a real answer (``rev-list`` of an empty range), so it comes back as "".
    ``--no-optional-locks`` keeps a read from taking ``index.lock`` under the agent's own git.
    Git prints path names and messages as UTF-8 whatever the platform, so stdout is decoded as
    UTF-8; Windows' locale code page would turn ``café`` into ``cafÃ©``.

    Args:
        cwd: The directory git runs in.
        *args: The git subcommand and its arguments.
    """
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", cwd, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None
