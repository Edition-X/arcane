"""The documentation a stranger follows has to stay true.

Links must resolve and the install commands must name a distribution that
actually exists. Both have been wrong here before: install docs once pointed at
PyPI's unrelated ``arcane`` package, and later froze on a tag that fifteen
releases had already passed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_DOCS = (ROOT / "README.md", ROOT / "docs" / "README.md", ROOT / "docs" / "installation.md")
MARKDOWN = sorted({*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")})

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# Written by the Docs workflow from the commit history at deploy time, so it is
# deliberately absent from the repository.
GENERATED = {"docs/changelog.md"}
PINNED_GIT_REF = re.compile(r"git\+https://github\.com/\S*?arcane[^\s\"']*@v[0-9][^\s\"')]*")


def _ident(path: Path) -> str:
    return str(path.relative_to(ROOT))


@pytest.mark.parametrize("path", INSTALL_DOCS, ids=_ident)
def test_install_docs_name_the_published_distribution(path: Path) -> None:
    """PyPI's ``arcane`` is an unrelated web framework. Ours is ``arcane-mcp``."""
    text = path.read_text(encoding="utf-8")
    assert "arcane-mcp" in text, f"{_ident(path)} never names the distribution"
    assert "uv tool install arcane\n" not in text
    assert "pip install arcane\n" not in text


@pytest.mark.parametrize("path", INSTALL_DOCS, ids=_ident)
def test_install_docs_do_not_pin_a_release_tag(path: Path) -> None:
    """A tag pinned in prose goes stale on the next release and nothing notices.

    Install from PyPI unpinned; people who want a specific version can read the
    release list.
    """
    stale = PINNED_GIT_REF.findall(path.read_text(encoding="utf-8"))
    assert not stale, f"{_ident(path)} pins a release tag that will go stale: {stale}"


@pytest.mark.parametrize("path", MARKDOWN, ids=_ident)
def test_relative_links_resolve(path: Path) -> None:
    broken = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")) or target == "/":
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if resolved.relative_to(ROOT).as_posix() in GENERATED:
            continue
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{_ident(path)} links to missing files: {broken}"
