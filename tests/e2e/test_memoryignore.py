"""``.memoryignore`` through the real CLI: a broken pattern is reported, the rest still redact."""

from __future__ import annotations

import re
import subprocess

from tests.e2e.conftest import ARCANE, Arcane


def test_invalid_pattern_warns_and_valid_ones_still_redact(arcane: Arcane) -> None:
    (arcane.home / ".memoryignore").write_text("# customer ids\nwidget-[0-9]+\ninvoice-([0-9]+\n", encoding="utf-8")

    saved = subprocess.run(
        [ARCANE, "save", "--title", "Refund", "--what", "Refunded widget-42 on invoice-7", "--category", "context"],
        cwd=arcane.repo,
        env=arcane.env("core"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "line 3: 'invoice-([0-9]+' is not a valid regex" in saved.stderr

    memory_id = re.search(r"\(id: ([0-9a-f-]+)\)", saved.stdout)
    assert memory_id is not None, saved.stdout
    [(what,)] = arcane.sql("SELECT what FROM memories WHERE id = ?", (memory_id.group(1),))
    assert what == "Refunded [REDACTED] on invoice-7"
