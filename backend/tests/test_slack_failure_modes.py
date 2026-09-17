"""Failure-mode tests for the Slack plugin.

Covers the "do these errors abort the whole harvest or just log + continue?"
contracts the orchestrator relies on.
"""

from __future__ import annotations

import pytest

# Slack is not enabled in this build, so `slack-sdk` moved to the optional
# `slack` extra (see pyproject.toml + src/sources.py). The plugin code under
# test imports it at module level, so skip the file rather than fail
# collection on a default install. `uv sync --extra all-sources` runs these.
pytest.importorskip("slack_sdk")

from unittest.mock import AsyncMock


from src.harvester.slack import ChannelSpec, SlackConfig, SlackHarvesterPlugin
from src.harvester.slack.client import (
    SlackAPIError,
    SlackAuthError,
    SlackClient,
    _RetryableSlackError,
)


def _make_plugin(channels: list[ChannelSpec]) -> tuple[SlackHarvesterPlugin, AsyncMock]:
    cfg = SlackConfig(channels=channels)
    mock_client = AsyncMock(spec=SlackClient)
    plugin = SlackHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


async def test_channel_not_found_skips_channel_continues_with_others(caplog):
    plugin, mock = _make_plugin([
        ChannelSpec(id="C_gone"),
        ChannelSpec(id="C_ok"),
    ])

    async def info(channel: str):
        if channel == "C_gone":
            raise SlackAPIError("channel_not_found", slack_error="channel_not_found")
        return {"id": "C_ok", "name": "general"}

    mock.conversations_info.side_effect = info
    mock.conversations_history.return_value = {
        "messages": [{"ts": "1.0", "user": "U1", "text": "x"}],
        "has_more": False,
    }
    caplog.set_level("WARNING")
    refs = await plugin.list_documents()
    # Bad channel skipped, good channel emitted normally.
    assert all("C_ok" in r.source_id for r in refs)
    assert refs  # we got something
    assert any("C_gone" in rec.message for rec in caplog.records)


async def test_name_resolution_failure_degrades_not_aborts(caplog):
    """A users.info failure during pre-resolve should warn-log + leave raw ID."""
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.conversations_info.return_value = {"id": "C1", "name": "general"}
    mock.conversations_replies.return_value = {
        "messages": [{"ts": "1.0", "user": "U1", "text": "ping <@U999>"}],
        "has_more": False,
    }
    # users.info fails — should NOT raise, just degrade.
    mock.users_info.side_effect = SlackAuthError("missing_scope", slack_error="missing_scope")
    from src.harvester import DocRef
    from datetime import datetime, timezone
    doc_ref = DocRef(
        source_id="slack:C1:thread:1.0",
        title="x",
        source_type="slack",
        modified_at=datetime.now(tz=timezone.utc),
        metadata={"document_type": "thread", "channel_id": "C1", "thread_ts": "1.0"},
    )
    raw = await plugin.fetch_document(doc_ref)
    # Fetch succeeded — no exception bubbled.
    assert raw.content


async def test_retryable_error_subclass_lineage():
    """retry-exhausted failures should still be catchable as the base SlackAPIError."""
    exc = _RetryableSlackError("temporarily down", slack_error="server_error", retry_after=1.0)
    assert isinstance(exc, SlackAPIError)
    assert exc.retry_after == 1.0


async def test_auth_error_subclass_lineage():
    exc = SlackAuthError("invalid_auth", slack_error="invalid_auth")
    assert isinstance(exc, SlackAPIError)


async def test_warmup_failure_is_non_fatal(caplog):
    """test_connection must succeed even if the cache warmup hits an error."""
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.auth_test.return_value = {"team": "Acme", "user": "alice"}
    mock.users_list.side_effect = SlackAPIError("server_error")
    caplog.set_level("WARNING")
    status = await plugin.test_connection()
    assert status.healthy is True
