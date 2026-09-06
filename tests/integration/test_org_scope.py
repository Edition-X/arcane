"""Integration tests for org/company scope (Global → Org → Project)."""

from __future__ import annotations

import json

from arcane.domain.models import RawMemoryInput
from arcane.mcp_server.tools.memory_tools import handle_context, handle_save, handle_search
from arcane.services.memory import MemoryService
from tests.conftest import make_memory_dict


def _seed_layers(repo):
    """Insert one memory in each layer of org 'acme' plus a foreign-org memory."""
    repo.insert(make_memory_dict(title="Repo fact", what="repo specific knowledge", org="acme", project="widget"))
    repo.insert(make_memory_dict(title="Company fact", what="company wide convention", org="acme", project=""))
    repo.insert(make_memory_dict(title="Universal fact", what="applies everywhere", org="global", project=""))
    repo.insert(make_memory_dict(title="Other repo", what="different company knowledge", org="other", project="thing"))


class TestRepoScopePersistence:
    def test_insert_persists_org(self, memory_repo):
        mem = make_memory_dict(org="acme", project="widget")
        memory_repo.insert(mem)
        fetched = memory_repo.get(mem["id"])
        assert fetched["org"] == "acme"

    def test_missing_org_defaults_empty(self, memory_repo):
        mem = make_memory_dict()  # no org key
        memory_repo.insert(mem)
        fetched = memory_repo.get(mem["id"])
        assert fetched["org"] == ""


class TestRepoScopedRetrieval:
    def test_list_recent_returns_chain(self, memory_repo):
        _seed_layers(memory_repo)
        rows = memory_repo.list_recent(limit=10, org="acme", project="widget")
        titles = {r["title"] for r in rows}
        assert "Repo fact" in titles  # project layer
        assert "Company fact" in titles  # org layer
        assert "Universal fact" in titles  # global layer
        assert "Other repo" not in titles  # foreign org excluded

    def test_list_recent_project_first_ordering(self, memory_repo):
        _seed_layers(memory_repo)
        rows = memory_repo.list_recent(limit=10, org="acme", project="widget")
        assert rows[0]["title"] == "Repo fact"
        assert rows[0]["scope_rank"] == 3

    def test_include_global_false_excludes_global(self, memory_repo):
        _seed_layers(memory_repo)
        rows = memory_repo.list_recent(limit=10, org="acme", project="widget", include_global=False)
        titles = {r["title"] for r in rows}
        assert "Universal fact" not in titles
        assert "Repo fact" in titles

    def test_include_org_false_excludes_org_layer(self, memory_repo):
        _seed_layers(memory_repo)
        rows = memory_repo.list_recent(limit=10, org="acme", project="widget", include_org=False)
        titles = {r["title"] for r in rows}
        assert "Company fact" not in titles
        assert "Repo fact" in titles

    def test_count_scoped_union(self, memory_repo):
        _seed_layers(memory_repo)
        # project + org + global of 'acme' = 3, foreign 'other' excluded
        assert memory_repo.count(org="acme", project="widget") == 3

    def test_fts_search_scoped(self, memory_repo):
        _seed_layers(memory_repo)
        rows = memory_repo.fts_search("knowledge convention everywhere", limit=10, org="acme", project="widget")
        titles = {r["title"] for r in rows}
        assert "Other repo" not in titles

    def test_legacy_project_filter_unchanged(self, memory_repo):
        """Calling without org keeps the old project-only behaviour."""
        memory_repo.insert(make_memory_dict(title="Legacy", what="x", project="p1"))
        memory_repo.insert(make_memory_dict(title="Legacy2", what="x", project="p2"))
        rows = memory_repo.list_recent(project="p1")
        assert len(rows) == 1
        assert "scope_rank" not in rows[0]


class TestServiceScope:
    def test_save_org_level(self, container):
        svc = MemoryService(container)
        svc.save(RawMemoryInput(title="Org wide", what="convention"), org="acme", project="")
        rows = container.memory_repo.list_recent(org="acme", project="widget")
        assert any(r["title"] == "Org wide" and r["scope_rank"] == 2 for r in rows)

    def test_get_context_layered_with_global_cap(self, container):
        svc = MemoryService(container)
        repo = container.memory_repo
        # 4 global memories, but cap should trim them in a context load
        for i in range(4):
            repo.insert(make_memory_dict(title=f"Global {i}", what="g", org="global", project=""))
        repo.insert(make_memory_dict(title="Proj", what="p", org="acme", project="widget"))
        results, total = svc.get_context(limit=10, org="acme", project="widget", global_cap=2)
        global_count = sum(1 for r in results if r.get("scope_rank") == 1)
        assert global_count <= 2
        assert any(r["title"] == "Proj" for r in results)


class TestHandlerScope:
    def test_save_scope_global(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_save(svc, title="Universal", what="everywhere", scope="global"))
        assert result["scope"]["org"] == "global"
        assert result["scope"]["project"] == ""

    def test_save_scope_org(self, container):
        svc = MemoryService(container)
        result = json.loads(handle_save(svc, title="Company norm", what="convention", scope="org", org="acme"))
        assert result["scope"]["org"] == "acme"
        assert result["scope"]["project"] == ""

    def test_context_echoes_scope(self, container):
        svc = MemoryService(container)
        handle_save(svc, title="Repo thing", what="knowledge", org="acme", project="widget")
        result = json.loads(handle_context(svc, org="acme", project="widget"))
        assert result["scope"]["org"] == "acme"
        assert result["scope"]["project"] == "widget"

    def test_context_includes_org_and_global_layers(self, container):
        svc = MemoryService(container)
        handle_save(svc, title="Proj fact", what="repo", org="acme", project="widget")
        handle_save(svc, title="Org fact", what="company", scope="org", org="acme")
        handle_save(svc, title="Global fact", what="universal", scope="global")
        result = json.loads(handle_context(svc, org="acme", project="widget", limit=10))
        titles = {m["title"] for m in result["memories"]}
        assert {"Proj fact", "Org fact", "Global fact"} <= titles

    def test_search_results_include_org(self, container):
        svc = MemoryService(container)
        handle_save(svc, title="Findable", what="searchme", org="acme", project="widget")
        # org is a full-only field now that memory_search defaults to standard detail.
        results = json.loads(handle_search(svc, query="searchme", org="acme", project="widget", detail="full"))
        assert results[0]["org"] == "acme"
