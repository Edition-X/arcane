"""A broken ``config.yaml`` has to say what is wrong, through the CLI and the server.

Falling back to defaults is not an option: a dropped ``orgs`` mapping files
memories under a different org, where scoped recall never finds them again. So
every one of these cases must fail loudly and name the file.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.e2e.conftest import ARCANE, Arcane

BROKEN = {
    "invalid YAML": ("embedding:\n  provider: [unclosed\n", "is not valid YAML"),
    "a non-slug mapped org": ("orgs:\n  remotes:\n    Acme: 'Not A Slug'\n", "orgs.remotes"),
    "a non-slug default org": ("orgs:\n  default: 'two words'\n", "orgs.default"),
    "an unknown embedding provider": ("embedding:\n  provider: ollamaa\n", "embedding.provider"),
    "a top-level list": ("- not\n- a mapping\n", "must contain a mapping"),
}


@pytest.mark.parametrize("case", list(BROKEN), ids=list(BROKEN))
def test_cli_reports_the_problem_without_a_traceback(arcane: Arcane, case: str) -> None:
    contents, expected = BROKEN[case]
    (arcane.home / "config.yaml").write_text(contents, encoding="utf-8")

    result = subprocess.run(
        [ARCANE, "search", "anything"],
        cwd=arcane.repo,
        env=arcane.env("core"),
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "config.yaml" in result.stderr
    assert expected in result.stderr


def test_server_refuses_to_start_and_says_why(arcane: Arcane) -> None:
    (arcane.home / "config.yaml").write_text("orgs:\n  default: 'two words'\n", encoding="utf-8")

    result = subprocess.run(
        [ARCANE, "mcp"],
        cwd=arcane.repo,
        env=arcane.env("core"),
        capture_output=True,
        text=True,
        input="",
        timeout=30,
    )

    assert result.returncode != 0
    assert "Arcane cannot start" in result.stderr
    assert "orgs.default" in result.stderr


def test_a_valid_config_still_loads(arcane: Arcane) -> None:
    (arcane.home / "config.yaml").write_text(
        "orgs:\n  remotes:\n    Acme: acme-corp\n  default: personal\nembedding:\n  provider: none\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [ARCANE, "config"],
        cwd=arcane.repo,
        env=arcane.env("core"),
        capture_output=True,
        text=True,
        check=True,
    )

    assert "acme-corp" in result.stdout
