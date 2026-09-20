"""Tests for src.harvester.slack.names.NameCache."""

from __future__ import annotations

import pytest

# Slack is not enabled in this build, so `slack-sdk` moved to the optional
# `slack` extra (see pyproject.toml + src/sources.py). The plugin code under
# test imports it at module level, so skip the file rather than fail
# collection on a default install. `uv sync --extra all-sources` runs these.
pytest.importorskip("slack_sdk")

import time
from unittest.mock import AsyncMock

from src.harvester.slack.client import SlackAPIError, SlackAuthError, SlackClient
from src.harvester.slack.names import NameCache


@pytest.fixture
def mock_client():
    return AsyncMock(spec=SlackClient)


async def test_user_display_hits_api_once_on_first_miss(mock_client):
    mock_client.users_info.return_value = {"id": "U1", "profile": {"display_name_normalized": "alice"}}
    cache = NameCache(mock_client, ttl_seconds=3600)
    a = await cache.user_display("U1")
    b = await cache.user_display("U1")
    assert a == "@alice"
    assert b == "@alice"
    assert mock_client.users_info.call_count == 1


async def test_user_not_found_caches_tombstone_long_ttl(mock_client):
    err = SlackAPIError("user_not_found", slack_error="user_not_found")
    mock_client.users_info.side_effect = err
    cache = NameCache(mock_client, ttl_seconds=3600)
    display = await cache.user_display("U_missing")
    assert display == "[deleted user]"
    # Second lookup must not re-hit the API (tombstone TTL >> standard TTL).
    display2 = await cache.user_display("U_missing")
    assert display2 == "[deleted user]"
    assert mock_client.users_info.call_count == 1


async def test_user_api_failure_degrades_to_raw_id(mock_client):
    mock_client.users_info.side_effect = SlackAuthError("missing_scope", slack_error="missing_scope")
    cache = NameCache(mock_client, ttl_seconds=3600)
    out = await cache.user_display("U1")
    # Auth/scope error is not "user_not_found" → returns raw-id fallback `@U1`
    assert out == "@U1"


async def test_slack_connect_team_id_keyed_separately(mock_client):
    """Same user_id but different team_id must hit the API twice."""
    mock_client.users_info.return_value = {"id": "U1", "profile": {"display_name_normalized": "alice"}}
    cache = NameCache(mock_client, ttl_seconds=3600)
    await cache.user_display("U1", team_id=None)
    await cache.user_display("U1", team_id="T_other")
    assert mock_client.users_info.call_count == 2
    # team_id kwarg propagates
    second_call_kwargs = mock_client.users_info.call_args_list[1].kwargs
    assert second_call_kwargs.get("team_id") == "T_other"


async def test_channel_display_hits_api_once(mock_client):
    mock_client.conversations_info.return_value = {"id": "C1", "name": "general"}
    cache = NameCache(mock_client, ttl_seconds=3600)
    a = await cache.channel_display("C1")
    b = await cache.channel_display("C1")
    assert a == "#general"
    assert b == "#general"
    assert mock_client.conversations_info.call_count == 1


async def test_ttl_expiry_triggers_refetch(mock_client):
    mock_client.users_info.return_value = {"id": "U1", "profile": {"display_name_normalized": "alice"}}
    cache = NameCache(mock_client, ttl_seconds=1)
    await cache.user_display("U1")
    # Force the cache entry to be expired by rewinding the clock on the entry.
    cache._users[(None, "U1")].expires_at = time.time() - 1
    await cache.user_display("U1")
    assert mock_client.users_info.call_count == 2


async def test_snapshot_exports_flat_id_to_display_dict(mock_client):
    mock_client.users_info.return_value = {"id": "U1", "profile": {"display_name_normalized": "alice"}}
    mock_client.conversations_info.return_value = {"id": "C1", "name": "general"}
    cache = NameCache(mock_client, ttl_seconds=3600)
    await cache.user_display("U1")
    await cache.channel_display("C1")
    snap = cache.snapshot()
    assert snap["U1"] == "@alice"
    assert snap["C1"] == "#general"


async def test_warmup_workspace_users_paginates_and_fills_cache(mock_client):
    mock_client.users_list.side_effect = [
        {"members": [{"id": "U1", "profile": {"display_name_normalized": "alice"}}],
         "response_metadata": {"next_cursor": "abc"}},
        {"members": [{"id": "U2", "profile": {"display_name_normalized": "bob"}}],
         "response_metadata": {"next_cursor": ""}},
    ]
    cache = NameCache(mock_client, ttl_seconds=3600)
    await cache.warmup_workspace_users()
    snap = cache.snapshot()
    assert snap["U1"] == "@alice"
    assert snap["U2"] == "@bob"
    assert mock_client.users_list.call_count == 2
