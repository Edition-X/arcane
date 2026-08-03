"""Markdown rendering and session file writing for memories."""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arcane.domain.enums import CATEGORY_HEADINGS, Category


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

    return "\n".join(lines)


def write_session_memory(
    vault_project_dir: str,
    mem: dict[str, Any],
    date_str: str,
    details: str | None = None,
) -> str:
    """Create or append to a session file without losing concurrent writes."""
    file_path = Path(vault_project_dir) / f"{date_str}-session.md"
    section_content = render_section(mem, details)

    with _file_lock(file_path):
        if not file_path.exists():
            content = _create_new_session_file(mem, date_str, section_content)
        else:
            content = file_path.read_text()
            content = _append_to_session_file(content, mem, section_content)
        _atomic_write(file_path, content)

    return str(file_path)


@contextmanager
def _file_lock(file_path: Path) -> Iterator[None]:
    """Use a sibling lock file so independent MCP processes serialize writes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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


def remove_session_memory(file_path: str, memory_id: str, title: str) -> bool:
    """Remove one persisted memory section from its Markdown mirror."""
    path = Path(file_path)
    if not path.exists():
        return False

    with _file_lock(path):
        content = path.read_text()
        marker = f"<!-- arcane-memory:{memory_id} -->"
        start = content.find(marker)
        if start < 0:
            # Older session files predate stable memory markers.
            start = content.find(f"### {title}")
        if start < 0:
            return False

        heading = content.find(f"### {title}", start)
        if heading < 0:
            return False
        next_heading = re.search(r"(?m)^(?:### |## )", content[heading + len(f"### {title}") :])
        end = heading + len(f"### {title}") + next_heading.start() if next_heading else len(content)
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

    if f"## {category_heading}" in body:
        return _append_under_existing_category(body, category_heading, section_content)
    else:
        return _insert_new_category(body, category, category_heading, section_content)


def _append_under_existing_category(body: str, category_heading: str, section_content: str) -> str:
    lines = body.split("\n")
    result_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        result_lines.append(line)

        if line == f"## {category_heading}":
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                result_lines.append(lines[i])
                i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                result_lines.append(lines[i])
                i += 1
            result_lines.append("")
            result_lines.append(section_content)
            continue

        i += 1

    return "\n".join(result_lines) + "\n"


def _insert_new_category(body: str, category: str, category_heading: str, section_content: str) -> str:
    category_order = [c.value for c in Category]
    target_index = category_order.index(category) if category in category_order else len(category_order)

    lines = body.split("\n")
    insert_position = len(lines)

    for i, line in enumerate(lines):
        if line.startswith("## "):
            heading_text = line[3:].strip()
            for cat_val, cat_heading in CATEGORY_HEADINGS.items():
                if cat_heading == heading_text:
                    cat_index = category_order.index(cat_val) if cat_val in category_order else len(category_order)
                    if cat_index > target_index:
                        insert_position = i
                        break
            if insert_position < len(lines):
                break

    new_lines = lines[:insert_position] + [f"## {category_heading}", "", section_content, ""] + lines[insert_position:]
    return "\n".join(new_lines).rstrip() + "\n"
