"""Unit tests for scope resolution (Global → Org → Project)."""

from __future__ import annotations

from arcane.domain.scope import (
    DEFAULT_ORG,
    GLOBAL_ORG,
    Scope,
    canonicalize_project,
    collapse_project_variant,
    resolve_scope,
    resolve_write_scope,
    slugify,
)
from arcane.infra.config import ArcaneConfig, OrgsConfig, ProjectsConfig


class TestSlugify:
    def test_lowercases_and_dashes(self):
        assert slugify("Edition X") == "edition-x"
        assert slugify("Sunrise-Robotics") == "sunrise-robotics"

    def test_collapses_separators(self):
        assert slugify("sunrise_robot_sw") == "sunrise-robot-sw"
        assert slugify("  Edition-X.github.io ") == "edition-x-github-io"

    def test_empty(self):
        assert slugify("") == ""
        assert slugify("   ") == ""


class TestCanonicalizeProject:
    def test_strips_owner_prefix(self):
        assert canonicalize_project("Sunrise-Robotics/monitoring-config") == "monitoring-config"

    def test_plain_name(self):
        assert canonicalize_project("monitoring-config") == "monitoring-config"

    def test_slugifies(self):
        assert canonicalize_project("Edition X") == "edition-x"


class TestCanonicalizeProjectAliases:
    def test_alias_applied(self):
        aliases = {"grafana-usage-report": "grafana-usage-automation"}
        assert canonicalize_project("grafana-usage-report", aliases) == "grafana-usage-automation"

    def test_alias_key_matched_after_normalisation(self):
        aliases = {"Grafana Usage Report": "grafana-usage-automation"}
        assert canonicalize_project("grafana-usage-report", aliases) == "grafana-usage-automation"

    def test_alias_value_normalised(self):
        aliases = {"foo": "Foo Bar"}
        assert canonicalize_project("foo", aliases) == "foo-bar"

    def test_owner_prefix_stripped_before_alias_lookup(self):
        aliases = {"monitoring-config": "monitoring"}
        assert canonicalize_project("Sunrise-Robotics/monitoring-config", aliases) == "monitoring"

    def test_unaliased_name_passes_through(self):
        aliases = {"other": "something"}
        assert canonicalize_project("monitoring-config", aliases) == "monitoring-config"

    def test_none_and_empty_aliases_are_noops(self):
        assert canonicalize_project("Edition X", None) == "edition-x"
        assert canonicalize_project("Edition X", {}) == "edition-x"
        assert canonicalize_project("", {"a": "b"}) == ""


def _config(**orgs) -> ArcaneConfig:
    return ArcaneConfig(orgs=OrgsConfig(**orgs))


class TestResolveScope:
    def test_remote_owner_maps_to_org(self):
        cfg = _config(remotes={"Sunrise-Robotics": "sunrise-robotics"})
        sc = resolve_scope("/x", cfg, _remote=("Sunrise-Robotics", "monitoring-config"))
        assert sc == Scope(org="sunrise-robotics", project="monitoring-config")

    def test_unmapped_owner_is_slugified(self):
        cfg = _config()
        sc = resolve_scope("/x", cfg, _remote=("Edition-X", "arcane"))
        assert sc.org == "edition-x"
        assert sc.project == "arcane"

    def test_no_remote_falls_back_to_default_org(self, monkeypatch, tmp_path):
        monkeypatch.setattr("arcane.domain.scope.git_remote_info", lambda cwd: (None, None))
        d = tmp_path / "playground"
        d.mkdir()
        sc = resolve_scope(str(d), _config())
        assert sc.org == DEFAULT_ORG  # "personal"
        assert sc.project == "playground"

    def test_override_takes_precedence(self):
        cfg = _config(
            remotes={"Sunrise-Robotics": "sunrise-robotics"},
            overrides={"finance-wiki": "personal"},
        )
        sc = resolve_scope("/x", cfg, _remote=("Sunrise-Robotics", "finance-wiki"))
        assert sc.org == "personal"
        assert sc.project == "finance-wiki"

    def test_global_is_reserved(self):
        assert GLOBAL_ORG == "global"

    def test_applies_project_alias_from_remote_repo(self):
        cfg = ArcaneConfig(projects=ProjectsConfig(aliases={"grafana-usage-report": "grafana-usage-automation"}))
        sc = resolve_scope("/x", cfg, _remote=("Edition-X", "grafana-usage-report"))
        assert sc.project == "grafana-usage-automation"

    def test_applies_project_alias_from_cwd_basename(self, monkeypatch, tmp_path):
        monkeypatch.setattr("arcane.domain.scope.git_remote_info", lambda cwd: (None, None))
        d = tmp_path / "grafana-usage-report"
        d.mkdir()
        cfg = ArcaneConfig(projects=ProjectsConfig(aliases={"grafana-usage-report": "grafana-usage-automation"}))
        sc = resolve_scope(str(d), cfg)
        assert sc.project == "grafana-usage-automation"

    def test_org_override_matches_aliased_project(self):
        cfg = ArcaneConfig(
            orgs=OrgsConfig(overrides={"grafana-usage-automation": "personal"}),
            projects=ProjectsConfig(aliases={"grafana-usage-report": "grafana-usage-automation"}),
        )
        sc = resolve_scope("/x", cfg, _remote=("Sunrise-Robotics", "grafana-usage-report"))
        assert sc.org == "personal"
        assert sc.project == "grafana-usage-automation"


class TestCollapseProjectVariant:
    def test_worktree_suffix_collapses(self):
        assert collapse_project_variant("sunrise-robot-sw-inf613", "sunrise-robot-sw") == "sunrise-robot-sw"

    def test_identical_is_noop(self):
        assert collapse_project_variant("sunrise-robot-sw", "sunrise-robot-sw") == "sunrise-robot-sw"

    def test_unrelated_project_untouched(self):
        assert collapse_project_variant("monitoring-config", "sunrise-robot-sw") == "monitoring-config"

    def test_no_dash_separator_does_not_collapse(self):
        assert collapse_project_variant("sunrise-robot-sw2", "sunrise-robot-sw") == "sunrise-robot-sw2"

    def test_empty_explicit_or_resolved_is_noop(self):
        assert collapse_project_variant("", "x") == ""
        assert collapse_project_variant("x", "") == "x"


class TestResolveWriteScope:
    def test_explicit_project_keeps_repo_org_and_canonicalizes(self):
        cfg = ArcaneConfig(projects=ProjectsConfig(aliases={"legacy-widget": "widget"}))

        scope = resolve_write_scope("legacy-widget", cfg, repo_path="/repos/widget", _remote=("Acme", "widget"))

        assert scope == Scope(org="acme", project="widget")

    def test_repo_path_supplies_default_project_and_org(self):
        scope = resolve_write_scope(None, _config(), repo_path="/repos/widget", _remote=("Acme", "widget"))

        assert scope == Scope(org="acme", project="widget")

    def test_worktree_variant_collapses_to_git_resolved_project(self):
        cfg = _config(remotes={"Sunrise-Robotics": "sunrise-robotics"})

        scope = resolve_write_scope("sunrise_robot_sw-inf613", cfg, _remote=("Sunrise-Robotics", "sunrise-robot-sw"))

        assert scope.project == "sunrise-robot-sw"

    def test_genuinely_different_project_still_wins(self):
        cfg = _config(remotes={"Sunrise-Robotics": "sunrise-robotics"})

        scope = resolve_write_scope("monitoring-config", cfg, _remote=("Sunrise-Robotics", "sunrise-robot-sw"))

        assert scope.project == "monitoring-config"


class TestOrgsConfig:
    def test_defaults(self):
        c = OrgsConfig()
        assert c.default == "personal"
        assert c.remotes == {}
        assert c.overrides == {}

    def test_loaded_into_arcane_config(self):
        cfg = ArcaneConfig.model_validate({"orgs": {"remotes": {"Acme": "acme"}, "default": "personal"}})
        assert cfg.orgs.remotes["Acme"] == "acme"


class TestProjectsConfig:
    def test_defaults(self):
        c = ProjectsConfig()
        assert c.aliases == {}

    def test_default_on_arcane_config(self):
        assert ArcaneConfig().projects.aliases == {}

    def test_loaded_into_arcane_config(self):
        cfg = ArcaneConfig.model_validate(
            {"projects": {"aliases": {"grafana-usage-report": "grafana-usage-automation"}}}
        )
        assert cfg.projects.aliases["grafana-usage-report"] == "grafana-usage-automation"


class TestDedupConfig:
    def test_defaults(self):
        from arcane.infra.config import DedupConfig

        assert DedupConfig().threshold == 0.92

    def test_loaded_into_arcane_config(self):
        cfg = ArcaneConfig.model_validate({"dedup": {"threshold": 0.85}})
        assert cfg.dedup.threshold == 0.85

    def test_default_on_arcane_config(self):
        assert ArcaneConfig().dedup.threshold == 0.92
