"""Unit tests for search functions."""

from arcane.infra.search import apply_scope_bonus, merge_results


class TestMergeResults:
    def test_empty_inputs(self):
        assert merge_results([], []) == []

    def test_fts_only(self):
        fts = [
            {"id": "a", "title": "A", "score": 10.0},
            {"id": "b", "title": "B", "score": 5.0},
        ]
        result = merge_results(fts, [], limit=5)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[0]["score"] > result[1]["score"]

    def test_vec_only(self):
        vec = [
            {"id": "x", "title": "X", "score": 0.9},
            {"id": "y", "title": "Y", "score": 0.5},
        ]
        result = merge_results([], vec, limit=5)
        assert len(result) == 2
        assert result[0]["id"] == "x"

    def test_merged_overlap(self):
        fts = [{"id": "a", "title": "A", "score": 10.0}]
        vec = [{"id": "a", "title": "A", "score": 0.8}]
        result = merge_results(fts, vec, fts_weight=0.3, vec_weight=0.7, limit=5)
        assert len(result) == 1
        # Combined score: 0.3 * 1.0 + 0.7 * 1.0 = 1.0
        assert result[0]["score"] == pytest.approx(1.0)

    def test_limit_respected(self):
        fts = [{"id": str(i), "title": str(i), "score": float(i)} for i in range(10)]
        result = merge_results(fts, [], limit=3)
        assert len(result) == 3

    def test_disjoint_results(self):
        fts = [{"id": "a", "title": "A", "score": 5.0}]
        vec = [{"id": "b", "title": "B", "score": 0.9}]
        result = merge_results(fts, vec, fts_weight=0.3, vec_weight=0.7, limit=5)
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"a", "b"}


class TestScopeBonus:
    def test_project_bonus_breaks_ties(self):
        rows = [
            {"id": "org", "score": 0.9, "scope_rank": 2},
            {"id": "proj", "score": 0.9, "scope_rank": 3},
        ]
        ranked = apply_scope_bonus(rows)
        assert ranked[0]["id"] == "proj"

    def test_strong_org_hit_beats_weak_project_hit(self):
        """Bias, not hard gate: a much stronger org hit still wins."""
        rows = [
            {"id": "weak_proj", "score": 0.50, "scope_rank": 3},
            {"id": "strong_org", "score": 1.00, "scope_rank": 2},
        ]
        ranked = apply_scope_bonus(rows)
        assert ranked[0]["id"] == "strong_org"

    def test_no_scope_rank_is_noop(self):
        rows = [{"id": "a", "score": 0.5}, {"id": "b", "score": 0.9}]
        ranked = apply_scope_bonus(rows)
        assert ranked[0]["id"] == "b"
        assert ranked[0]["score"] == 0.9


import pytest
