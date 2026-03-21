"""Blog post structured brief generator.

Generates a structured markdown brief from a journey (with linked memories and
artifacts) or from a collection of project memories. Designed to be fed into
an LLM for final prose generation — this plugin provides structure, not prose.
"""

from __future__ import annotations

import json
from typing import Any


class BlogGenerator:
    name = "blog"

    def generate(self, context: dict[str, Any]) -> str:
        journey = context.get("journey")
        if journey:
            return self._from_journey(journey)

        memories = context.get("memories")
        if memories:
            project = context.get("project", "unknown")
            return self._from_memories(memories, project)

        return ""

    def _from_journey(self, journey: dict) -> str:
        lines = [
            f"# Blog Brief: {journey['title']}",
            "",
            f"**Project:** {journey.get('project', '')}",
            f"**Status:** {journey.get('status', '')}",
            f"**Started:** {journey.get('started_at', '')[:10]}",
        ]

        if journey.get("completed_at"):
            lines.append(f"**Completed:** {journey['completed_at'][:10]}")

        if journey.get("summary"):
            lines.append(f"\n## Summary\n{journey['summary']}")

        memories = journey.get("linked_memories", [])
        if memories:
            lines.append("\n## Decision Timeline\n")
            for item in memories:
                mem = item["memory"]
                rel = item.get("relation", "related")
                cat = mem.get("category", "note")
                lines.append(f"### [{cat}] {mem['title']}")
                lines.append(f"**What:** {mem.get('what', '')}")
                if mem.get("why"):
                    lines.append(f"**Why:** {mem['why']}")
                if mem.get("impact"):
                    lines.append(f"**Impact:** {mem['impact']}")

                tags = mem.get("tags", "")
                if isinstance(tags, str) and tags:
                    try:
                        tags = json.loads(tags)
                    except (json.JSONDecodeError, TypeError):
                        tags = []
                if tags:
                    lines.append(f"**Tags:** {', '.join(tags)}")

                lines.append(f"*Relation: {rel}*")
                lines.append("")

        artifacts = journey.get("linked_artifacts", [])
        if artifacts:
            lines.append("\n## Related Artifacts\n")
            for item in artifacts:
                art = item["artifact"]
                lines.append(f"- [{art.get('artifact_type', 'artifact')}] {art['title']}")
                if art.get("url"):
                    lines.append(f"  URL: {art['url']}")
                if art.get("external_id"):
                    lines.append(f"  ID: {art['external_id']}")

        lines.append("\n## Suggested Blog Outline\n")
        lines.append("1. **Problem/Motivation** — Why did this journey start?")
        lines.append("2. **Exploration** — What options were considered?")
        lines.append("3. **Decision** — What was chosen and why?")
        lines.append("4. **Implementation** — How was it built?")
        lines.append("5. **Results** — What was the outcome?")
        lines.append("6. **Lessons Learned** — What would you do differently?")

        return "\n".join(lines)

    def _from_memories(self, memories: list[dict], project: str) -> str:
        lines = [
            f"# Blog Brief: {project}",
            "",
            f"**Project:** {project}",
            f"**Memories:** {len(memories)}",
            "\n## Key Points\n",
        ]

        for mem in memories:
            title = mem.get("title", "Untitled")
            cat = mem.get("category", "note")
            lines.append(f"### [{cat}] {title}")
            lines.append(f"**What:** {mem.get('what', '')}")
            if mem.get("why"):
                lines.append(f"**Why:** {mem['why']}")
            if mem.get("impact"):
                lines.append(f"**Impact:** {mem['impact']}")
            lines.append("")

        return "\n".join(lines)
