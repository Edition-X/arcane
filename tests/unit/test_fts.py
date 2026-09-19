"""Unit tests for FTS5 query construction."""

from arcane.infra.db.fts import prefix_or_query


def test_each_term_becomes_a_quoted_prefix_query():
    assert prefix_or_query("tool profiles") == '"tool"* OR "profiles"*'


def test_blank_text_has_no_query():
    assert prefix_or_query("   ") is None


def test_double_quotes_are_escaped():
    assert prefix_or_query('say "hi') == '"say"* OR """hi"*'
