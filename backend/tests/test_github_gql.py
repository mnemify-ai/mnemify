"""Tests for src.harvester.github.gql variables + parsers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.harvester.github.gql import (
    DISCUSSION_DETAIL_QUERY,
    DISCUSSIONS_QUERY,
    build_discussion_detail_variables,
    build_discussion_list_variables,
    parse_iso8601,
    split_repo,
)


# ── split_repo ────────────────────────────────────────────────────


def test_split_repo_happy_path():
    assert split_repo("octocat/Hello-World") == ("octocat", "Hello-World")


def test_split_repo_rejects_malformed():
    with pytest.raises(ValueError):
        split_repo("just-a-name")
    with pytest.raises(ValueError):
        split_repo("/missing")
    with pytest.raises(ValueError):
        split_repo("missing/")


# ── build_discussion_list_variables ───────────────────────────────


def test_list_variables_carry_owner_name_and_cursor():
    out = build_discussion_list_variables("octocat/Hello-World", cursor=None)
    assert out == {"owner": "octocat", "name": "Hello-World", "cursor": None}
    out2 = build_discussion_list_variables("octocat/Hello-World", cursor="cursor-xyz")
    assert out2["cursor"] == "cursor-xyz"


# ── build_discussion_detail_variables ─────────────────────────────


def test_detail_variables_coerce_number_to_int():
    out = build_discussion_detail_variables("o/r", "42", comments_cursor=None)
    assert out["number"] == 42
    assert out["commentsCursor"] is None


def test_detail_variables_carry_comments_cursor():
    out = build_discussion_detail_variables("o/r", 1, comments_cursor="abc")
    assert out["commentsCursor"] == "abc"


# ── Query string sanity ───────────────────────────────────────────


def test_discussions_query_orders_by_updated_at_desc():
    assert "UPDATED_AT" in DISCUSSIONS_QUERY
    assert "DESC" in DISCUSSIONS_QUERY


def test_discussions_query_uses_owner_name_cursor_variables():
    assert "$owner: String!" in DISCUSSIONS_QUERY
    assert "$name: String!" in DISCUSSIONS_QUERY
    assert "$cursor: String" in DISCUSSIONS_QUERY


def test_detail_query_fetches_comments_with_replies():
    assert "comments(" in DISCUSSION_DETAIL_QUERY
    assert "replies(" in DISCUSSION_DETAIL_QUERY
    assert "$number: Int!" in DISCUSSION_DETAIL_QUERY


# ── parse_iso8601 ─────────────────────────────────────────────────


def test_parse_iso8601_handles_trailing_z():
    out = parse_iso8601("2026-05-13T14:22:00Z")
    assert out is not None
    assert out.tzinfo is not None
    assert out == datetime(2026, 5, 13, 14, 22, 0, tzinfo=timezone.utc)


def test_parse_iso8601_returns_none_on_garbage():
    assert parse_iso8601(None) is None
    assert parse_iso8601("not a date") is None
