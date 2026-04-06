"""MCP prompt definitions for Arcane."""

from __future__ import annotations

from typing import Any

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "recall",
        "description": "Search Arcane memory for past decisions, bugs, or patterns related to a topic.",
        "arguments": [
            {"name": "project", "description": "Project name to search within.", "required": False},
            {"name": "query", "description": "Topic or question to search for.", "required": True},
        ],
    },
    {
        "name": "catchup",
        "description": "Summarise recent engineering activity and decisions for a project.",
        "arguments": [
            {"name": "project", "description": "Project name.", "required": True},
            {"name": "limit", "description": "Number of recent memories to include (default: 10).", "required": False},
        ],
    },
    {
        "name": "journey",
        "description": "Show the full decision narrative for a journey — problem, exploration, and outcome.",
        "arguments": [
            {"name": "journey_id", "description": "Journey ID or prefix.", "required": True},
        ],
    },
]


def build_recall_prompt(args: dict[str, str]) -> dict:
    project = args.get("project", "the current project")
    query = args["query"]  # required — raise KeyError if missing
    return {
        "description": f"Search Arcane memory for: {query}",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Search Arcane memory in project '{project}' for information about: {query}\n\n"
                        "Use the memory_search tool with this query and summarise the most relevant results. "
                        "Include any decisions made, bugs fixed, or patterns discovered related to this topic."
                    ),
                },
            }
        ],
    }


def build_catchup_prompt(args: dict[str, str]) -> dict:
    project = args["project"]
    limit = args.get("limit", "10")
    return {
        "description": f"Catch up on recent activity in {project}",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Get me up to speed on recent engineering activity in project '{project}'.\n\n"
                        f"Use memory_context with project='{project}' and limit={limit} "
                        "to fetch the most recent memories. "
                        "Then summarise: key decisions made, bugs fixed, "
                        "patterns established, and any open questions."
                    ),
                },
            }
        ],
    }


def build_journey_prompt(args: dict[str, str]) -> dict:
    journey_id = args["journey_id"]
    return {
        "description": f"Show decision journey {journey_id}",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Show me the full decision journey for journey ID: {journey_id}\n\n"
                        "Retrieve the journey details and any linked memories or artifacts. "
                        "Present it as a narrative: what was the problem, what options were explored, "
                        "what was decided, and what was the outcome."
                    ),
                },
            }
        ],
    }
