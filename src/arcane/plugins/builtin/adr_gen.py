"""ADR (Architecture Decision Record) generator.

Generates a structured ADR from a decision memory and its details. Output is
markdown suitable for an ADR repository or further LLM refinement.
"""

from __future__ import annotations

import json
from typing import Any


class ADRGenerator:
    name = "adr"

    def generate(self, context: dict[str, Any]) -> str:
        memory = context.get("memory")
        if not memory:
            return ""

        details = context.get("details", "")
        title = memory.get("title", "Untitled Decision")
        what = memory.get("what", "")
        why = memory.get("why", "")
        impact = memory.get("impact", "")

        tags = memory.get("tags", "")
        if isinstance(tags, str) and tags:
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        tag_list = tags if isinstance(tags, list) else []

        lines = [
            f"# ADR: {title}",
            "",
            "## Status",
            "Accepted",
            "",
        ]

        # Tags as keywords
        if tag_list:
            lines.extend([
                "## Keywords",
                ", ".join(tag_list),
                "",
            ])

        lines.extend([
            "## Context",
            what or "No context provided.",
            "",
            "## Decision",
            why or "See details below.",
            "",
            "## Consequences",
            impact or "See details below.",
            "",
        ])

        if details:
            lines.extend([
                "## Details",
                details,
                "",
            ])

        # Add category-specific sections
        category = memory.get("category", "")
        if category == "decision" and not details:
            lines.extend([
                "## Details",
                "*No detailed analysis was captured for this decision.*",
                "*Consider adding: options considered, tradeoffs, and follow-up items.*",
                "",
            ])

        return "\n".join(lines)
