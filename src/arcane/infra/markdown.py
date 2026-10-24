"""Markdown rendering and session file writing for memories."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

if sys.platform == "win32":  # pragma: no cover - exercised by the Windows CI leg
    import msvcrt
else:
    import fcntl

from arcane.domain.enums import CATEGORY_HEADINGS, Category
from arcane.infra.redaction import redact, redact_values


def render_section(mem: dict[str, Any], details: str | None = None) -> str:
    """Render a single H3 section from a memory dict."""
    lines = []
    if mem.get("id"):
        lines.append(f"<!-- arcane-memory:{mem['id']} -->")
    lines.append(f"### {mem['title']}")
    lines.append(f"**What:** {mem['what']}")

    if mem.get("why"):
        lines.append(f"**Why:** {mem['why']}")
    if mem.get("impact"):
        lines.append(f"**Impact:** {mem['impact']}")
    if mem.get("source"):
        lines.append(f"**Source:** {mem['source']}")

    if details:
        lines.append("")
        lines.append("<details>")
        lines.append(details)
        lines.append("</details>")

    if mem.get("id"):
        lines.append(f"<!-- /arcane-memory:{mem['id']} -->")
    return "\n".join(lines)


def write_session_memory(
    vault_project_dir: str,
    mem: dict[str, Any],
    date_str: str,
    details: str | None = None,
    *,
    target_path: Path | None = None,
) -> str:
    """Create or append to a session file without losing concurrent writes."""
    mem = redact_values(mem)
    assert isinstance(mem, dict)
    details = redact(details) if details else details
    file_path = target_path or Path(vault_project_dir) / f"{date_str}-session.md"
    section_content = render_section(mem, details)

    with _file_lock(file_path):
        if not file_path.exists():
            content = _create_new_session_file(mem, date_str, section_content)
        else:
            content = file_path.read_text()
            bounds = _section_bounds(content, mem["id"], mem["title"])
            if bounds is None:
                content = _append_to_session_file(content, mem, section_content)
            else:
                start, end = bounds
                content = content[:start] + section_content + "\n\n" + content[end:].lstrip()
                frontmatter, body = _split_frontmatter(content)
                content = _update_frontmatter(frontmatter, mem) + "\n" + body
        _atomic_write(file_path, content)

    return str(file_path)


# How long to keep retrying a contended lock on Windows, which has no blocking
# equivalent of flock() that also releases cleanly on process death.
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_RETRY_SECONDS = 0.05


def _acquire(lock_file: IO[str]) -> None:
    if sys.platform == "win32":  # pragma: no cover - exercised by the Windows CI leg
        lock_file.seek(0)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(_LOCK_RETRY_SECONDS)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _release(lock_file: IO[str]) -> None:
    if sys.platform == "win32":  # pragma: no cover - exercised by the Windows CI leg
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _file_lock(file_path: Path) -> Iterator[None]:
    """Use a sibling lock file so independent MCP processes serialize writes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    with lock_path.open("a+") as lock_file:
        _acquire(lock_file)
        try:
            yield
        finally:
            _release(lock_file)


def _atomic_write(file_path: Path, content: str) -> None:
    """Replace the session file only after the complete new content is durable."""
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=file_path.parent, delete=False) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = temp_file.name
        os.replace(temp_path, file_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _structural_lines(content: str) -> Iterator[tuple[int, str]]:
    """Yield lines outside fenced code and details blocks with their offsets."""
    offset = 0
    depth = 0
    fence: str | None = None
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
        elif stripped.startswith("<details"):
            depth += 1
        elif stripped.startswith("</details>"):
            depth = max(0, depth - 1)
        elif depth == 0:
            yield offset, line.rstrip("\r\n")
        offset += len(line)


def _section_bounds(content: str, memory_id: str, title: str) -> tuple[int, int] | None:
    """Locate a complete memory, supporting old files without end markers."""
    marker = f"<!-- arcane-memory:{memory_id} -->"
    end_marker = f"<!-- /arcane-memory:{memory_id} -->"
    lines = list(_structural_lines(content))
    start = next((offset for offset, line in lines if line == marker), None)
    if start is None:
        start = next((offset for offset, line in lines if line == f"### {title}"), None)
    if start is None:
        return None
    seen_heading = False
    for offset, line in lines:
        if offset < start:
            continue
        if line == end_marker:
            return start, offset + len(line)
        if offset > start and (line.startswith("<!-- arcane-memory:") or line.startswith("## ")):
            return start, offset
        if line.startswith("### "):
            if seen_heading:
                return start, offset
            seen_heading = True
    return start, len(content)


def remove_session_memory(file_path: str, memory_id: str, title: str) -> bool:
    """Remove a complete memory without mistaking headings in details for peers."""
    path = Path(file_path)
    if not path.exists():
        return False
    with _file_lock(path):
        content = path.read_text()
        bounds = _section_bounds(content, memory_id, title)
        if bounds is None:
            return False
        start, end = bounds
        _atomic_write(path, content[:start].rstrip() + "\n\n" + content[end:].lstrip())
    return True


def _create_new_session_file(mem: dict[str, Any], date_str: str, section_content: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    sources = [mem["source"]] if mem.get("source") else []
    tags = sorted(mem.get("tags", []))

    lines = ["---"]
    lines.append(f"project: {mem['project']}")
    lines.append(f"sources: [{', '.join(sources)}]")
    lines.append(f"created: {now}")
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {date_str} Session")
    lines.append("")

    category = mem.get("category")
    if category and category in CATEGORY_HEADINGS:
        lines.append(f"## {CATEGORY_HEADINGS[category]}")
        lines.append("")

    lines.append(section_content)
    return "\n".join(lines) + "\n"


def _append_to_session_file(content: str, mem: dict[str, Any], section_content: str) -> str:
    frontmatter, body = _split_frontmatter(content)
    updated_frontmatter = _update_frontmatter(frontmatter, mem)
    updated_body = _insert_section_in_body(body, mem, section_content)
    return updated_frontmatter + "\n" + updated_body


def _split_frontmatter(content: str) -> tuple[str, str]:
    parts = content.split("---\n", 2)
    if len(parts) >= 3:
        return "---\n" + parts[1] + "---", parts[2]
    return "", content


def _update_frontmatter(frontmatter: str, mem: dict[str, Any]) -> str:
    lines = frontmatter.split("\n")
    existing_tags: list[str] = []
    existing_sources: list[str] = []

    for line in lines:
        if line.startswith("tags:"):
            match = re.search(r"\[(.*?)\]", line)
            if match and match.group(1).strip():
                existing_tags = [t.strip() for t in match.group(1).split(",")]
        elif line.startswith("sources:"):
            match = re.search(r"\[(.*?)\]", line)
            if match and match.group(1).strip():
                existing_sources = [s.strip() for s in match.group(1).split(",")]

    all_tags = sorted(set(existing_tags + mem.get("tags", [])))
    new_source = mem.get("source")
    all_sources = existing_sources.copy()
    if new_source and new_source not in all_sources:
        all_sources.append(new_source)

    updated_lines = []
    for line in lines:
        if line.startswith("tags:"):
            updated_lines.append(f"tags: [{', '.join(all_tags)}]")
        elif line.startswith("sources:"):
            updated_lines.append(f"sources: [{', '.join(all_sources)}]")
        else:
            updated_lines.append(line)
    return "\n".join(updated_lines)


def _insert_section_in_body(body: str, mem: dict[str, Any], section_content: str) -> str:
    category = mem.get("category")
    if not category or category not in CATEGORY_HEADINGS:
        return body.rstrip() + "\n\n" + section_content + "\n"

    category_heading = CATEGORY_HEADINGS[category]

    if any(line == f"## {category_heading}" for _, line in _structural_lines(body)):
        return _append_under_existing_category(body, category_heading, section_content)
    else:
        return _insert_new_category(body, category, category_heading, section_content)


def _append_under_existing_category(body: str, category_heading: str, section_content: str) -> str:
    headings = [(offset, line) for offset, line in _structural_lines(body) if line.startswith("## ")]
    start = next(offset for offset, line in headings if line == f"## {category_heading}")
    end = next((offset for offset, _ in headings if offset > start), len(body))
    return body[:end].rstrip() + "\n\n" + section_content + "\n\n" + body[end:].lstrip()


def _insert_new_category(body: str, category: str, category_heading: str, section_content: str) -> str:
    category_order = [c.value for c in Category]
    target_index = category_order.index(category) if category in category_order else len(category_order)
    insert_position = len(body)
    for offset, line in _structural_lines(body):
        if not line.startswith("## "):
            continue
        for cat_val, heading in CATEGORY_HEADINGS.items():
            if heading == line[3:].strip() and category_order.index(cat_val) > target_index:
                insert_position = offset
                break
        if insert_position < len(body):
            break
    section = f"## {category_heading}\n\n{section_content}\n\n"
    return body[:insert_position].rstrip() + "\n\n" + section + body[insert_position:].lstrip()
