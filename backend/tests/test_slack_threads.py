"""Tests for src.harvester.slack.threads.MessageExtractor pagination."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.harvester.slack.client import SlackClient
from src.harvester.slack.threads import MessageExtractor, _effective_modified_ts


@pytest.fixture
def mock_client():
    return AsyncMock(spec=SlackClient)


async def test_list_thread_starters_paginates_cursor(mock_client):
    mock_client.conversations_history.side_effect = [
        {"messages": [{"ts": "1.0", "user": "U1"}, {"ts": "2.0", "user": "U2", "thread_ts": "1.0"}],
         "has_more": True, "response_metadata": {"next_cursor": "abc"}},
        {"messages": [{"ts": "3.0", "user": "U3"}], "has_more": False},
    ]
    extractor = MessageExtractor(mock_client)
    results = []
    async for msg in extractor.list_thread_starters("C1", oldest=1000.0):
        results.append(msg)
    # The reply at ts=2.0 with thread_ts=1.0 must be filtered out (it's a reply).
    assert [m["ts"] for m in results] == ["1.0", "3.0"]
    assert mock_client.conversations_history.call_count == 2
    first_kwargs = mock_client.conversations_history.call_args_list[0].kwargs
    assert first_kwargs["oldest"] == 1000.0


async def test_list_thread_starters_dedups_repeated_ts(mock_client):
    """Slack occasionally re-yields a page during write bursts — must dedup."""
    mock_client.conversations_history.side_effect = [
        {"messages": [{"ts": "1.0", "user": "U1"}], "has_more": True,
         "response_metadata": {"next_cursor": "abc"}},
        {"messages": [{"ts": "1.0", "user": "U1"}, {"ts": "2.0", "user": "U2"}], "has_more": False},
    ]
    extractor = MessageExtractor(mock_client)
    results = [m async for m in extractor.list_thread_starters("C1")]
    assert [m["ts"] for m in results] == ["1.0", "2.0"]


async def test_get_thread_concatenates_paginated_replies(mock_client):
    mock_client.conversations_replies.side_effect = [
        {"messages": [{"ts": "1.0"}, {"ts": "2.0"}], "has_more": True,
         "response_metadata": {"next_cursor": "abc"}},
        {"messages": [{"ts": "3.0"}], "has_more": False},
    ]
    extractor = MessageExtractor(mock_client)
    out = await extractor.get_thread("C1", "1.0")
    assert [m["ts"] for m in out] == ["1.0", "2.0", "3.0"]


async def test_list_messages_in_day_uses_oldest_and_latest(mock_client):
    mock_client.conversations_history.return_value = {
        "messages": [{"ts": "1700000000.0001"}, {"ts": "1700000060.0001"}],
        "has_more": False,
    }
    extractor = MessageExtractor(mock_client)
    out = await extractor.list_messages_in_day("C1", date(2026, 5, 13))
    assert len(out) == 2
    kwargs = mock_client.conversations_history.call_args.kwargs
    # oldest = midnight UTC of that day; latest = +1 day
    assert kwargs["oldest"] == 1778630400.0  # 2026-05-13 00:00 UTC
    assert kwargs["latest"] == 1778716800.0  # 2026-05-14 00:00 UTC


async def test_list_active_days_returns_sorted_unique_dates(mock_client):
    mock_client.conversations_history.return_value = {
        "messages": [
            {"ts": "1778630400.0001"},  # 2026-05-13 00:00 UTC
            {"ts": "1778716799.0001"},  # 2026-05-13 23:59 UTC
            {"ts": "1778716800.0001"},  # 2026-05-14 00:00 UTC
        ],
        "has_more": False,
    }
    extractor = MessageExtractor(mock_client)
    days = await extractor.list_active_days("C1")
    assert days == [date(2026, 5, 13), date(2026, 5, 14)]


def test_effective_modified_ts_picks_edited_when_newer():
    msg = {"ts": "1.0", "edited": {"ts": "5.0"}}
    assert _effective_modified_ts(msg) == "5.0"


def test_effective_modified_ts_falls_back_to_ts():
    assert _effective_modified_ts({"ts": "1.0"}) == "1.0"
