"""Markdown rendering and session file writing for memories."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arcane.domain.enums import CATEGORY_HEADINGS, Category


def render_section(mem: dict[str, Any], details: str | None = None) -> str:
    """Render a single H3 section from a memory dict."""
    lines = [f"### {mem['title']}"]
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
    """Create or append to a session file."""
    file_path = Path(vault_project_dir) / f"{date_str}-session.md"
    section_content = render_section(mem, details)

    if not file_path.exists():
        content = _create_new_session_file(mem, date_str, section_content)
        file_path.write_text(content)
    else:
        content = file_path.read_text()
        updated_content = _append_to_session_file(content, mem, section_content)
        file_path.write_text(updated_content)

    return str(file_path)


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
