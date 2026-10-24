"""``.memoryignore`` through the real CLI: a broken pattern is reported, the rest still redact."""

from __future__ import annotations

import re
import subprocess

from tests.e2e.conftest import ARCANE, Arcane, Client


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


def test_pattern_matching_a_field_name_does_not_drop_the_field(arcane: Arcane) -> None:
    """A pattern matching a field *name* must not cost the save that field.

    ``redact_values`` once redacted mapping keys too, so ``\\w+_id`` renamed the
    ``journey_id`` key and the memory was stored with no journey link and no
    warning. ``title`` broke the save outright.
    """
    (arcane.home / ".memoryignore").write_text(r"\w+_id" "\n" r"title" "\n", encoding="utf-8")

    async def scenario(client: Client) -> tuple[dict, dict]:
        journey = await client.call("journey_start", title="Pattern journey")
        saved = await client.call(
            "memory_save",
            title="Linked under a key-matching pattern",
            what="the journey link must survive",
            category="context",
            journey_id=journey["id"],
        )
        return journey, saved

    journey, saved = arcane.run(scenario)

    assert saved["action"] == "created"
    links = arcane.sql(
        "SELECT source_id FROM relationships WHERE target_type = 'journey' AND target_id = ?",
        (journey["id"],),
    )
    assert links == [(saved["id"],)]


def test_pattern_lengthening_the_title_still_saves(arcane: Arcane) -> None:
    """Redaction replaces a span with a longer marker; that must not fail validation."""
    (arcane.home / ".memoryignore").write_text("acme\n", encoding="utf-8")
    title = "acme " * 11  # 55 chars in, well over 60 once each "acme" is replaced

    async def scenario(client: Client) -> dict:
        return await client.call(
            "memory_save", title=title.strip(), what="a long title that redaction grows", category="context"
        )

    saved = arcane.run(scenario)

    assert saved["action"] == "created"
    [(stored,)] = arcane.sql("SELECT title FROM memories WHERE id = ?", (saved["id"],))
    assert "acme" not in stored
    assert stored.startswith("[REDACTED]")
