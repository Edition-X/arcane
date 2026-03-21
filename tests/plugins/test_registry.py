"""Tests for the plugin discovery registry."""

from __future__ import annotations

from arcane.plugins.registry import discover_plugins


class TestPluginRegistry:
    def test_discover_ingestion_plugins(self):
        plugins = discover_plugins("arcane.plugins.ingestion")
        assert "git" in plugins
        assert "github_actions" in plugins
        assert "linear" in plugins

    def test_discover_intelligence_plugins(self):
        plugins = discover_plugins("arcane.plugins.intelligence")
        assert "ci_flakes" in plugins
        assert "velocity" in plugins

    def test_discover_content_plugins(self):
        plugins = discover_plugins("arcane.plugins.content")
        assert "blog" in plugins
        assert "adr" in plugins

    def test_discover_returns_classes(self):
        plugins = discover_plugins("arcane.plugins.ingestion")
        from arcane.plugins.builtin.git_ingest import GitIngestionPlugin
        assert plugins["git"] is GitIngestionPlugin

    def test_discover_unknown_group(self):
        plugins = discover_plugins("arcane.plugins.nonexistent")
        assert plugins == {}

    def test_all_plugins_conform_to_protocol(self):
        from arcane.plugins.protocols import ContentPlugin, IngestionPlugin, IntelligencePlugin

        for name, cls in discover_plugins("arcane.plugins.ingestion").items():
            instance = cls() if name == "git" else cls(api_key="k", team_id="t") if name == "linear" else cls(owner="o", repo="r")
            assert isinstance(instance, IngestionPlugin), f"{name} doesn't implement IngestionPlugin"

        for name, cls in discover_plugins("arcane.plugins.intelligence").items():
            instance = cls(artifact_repo=None) if name == "ci_flakes" else cls(artifact_repo=None, memory_repo=None, journey_repo=None)
            assert isinstance(instance, IntelligencePlugin), f"{name} doesn't implement IntelligencePlugin"

        for name, cls in discover_plugins("arcane.plugins.content").items():
            instance = cls()
            assert isinstance(instance, ContentPlugin), f"{name} doesn't implement ContentPlugin"
