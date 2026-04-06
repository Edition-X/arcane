"""Tests for MCP prompt builder functions."""

from __future__ import annotations

import pytest

from arcane.mcp_server.prompts import (
    PROMPTS,
    build_catchup_prompt,
    build_journey_prompt,
    build_recall_prompt,
)


class TestPromptList:
    def test_three_prompts_defined(self):
        names = {p["name"] for p in PROMPTS}
        assert names == {"recall", "catchup", "journey"}

    def test_each_prompt_has_description(self):
        for p in PROMPTS:
            assert p.get("description"), f"Prompt {p['name']} missing description"

    def test_recall_has_required_args(self):
        recall = next(p for p in PROMPTS if p["name"] == "recall")
        arg_names = {a["name"] for a in recall["arguments"]}
        assert "project" in arg_names
        assert "query" in arg_names

    def test_catchup_has_project_arg(self):
        catchup = next(p for p in PROMPTS if p["name"] == "catchup")
        arg_names = {a["name"] for a in catchup["arguments"]}
        assert "project" in arg_names

    def test_journey_has_journey_id_arg(self):
        journey = next(p for p in PROMPTS if p["name"] == "journey")
        arg_names = {a["name"] for a in journey["arguments"]}
        assert "journey_id" in arg_names


class TestPromptBuilders:
    def test_recall_contains_project_and_query(self):
        result = build_recall_prompt({"project": "arcane", "query": "authentication"})
        text = result["messages"][0]["content"]["text"]
        assert "arcane" in text
        assert "authentication" in text

    def test_catchup_contains_project(self):
        result = build_catchup_prompt({"project": "myproject", "limit": "5"})
        text = result["messages"][0]["content"]["text"]
        assert "myproject" in text

    def test_journey_contains_journey_id(self):
        result = build_journey_prompt({"journey_id": "abc-123-def"})
        text = result["messages"][0]["content"]["text"]
        assert "abc-123-def" in text

    def test_recall_missing_query_raises(self):
        with pytest.raises(KeyError):
            build_recall_prompt({"project": "x"})

    def test_recall_missing_project_uses_default(self):
        # project is optional — missing should not raise
        result = build_recall_prompt({"query": "something"})
        assert result["messages"]

    def test_catchup_default_limit(self):
        result = build_catchup_prompt({"project": "x"})
        text = result["messages"][0]["content"]["text"]
        assert "x" in text
