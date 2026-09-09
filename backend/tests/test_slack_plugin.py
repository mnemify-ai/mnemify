"""Tests for src.harvester.slack.plugin.SlackHarvesterPlugin."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from src.harvester.slack import (
    ChannelSpec,
    SlackConfig,
    SlackHarvesterPlugin,
)
from src.harvester.slack.client import SlackAuthError, SlackClient
from src.harvester.registry import create_plugin, registered_source_types


# ── Fixtures ──────────────────────────────────────────────────────


def _make_plugin(
    channels: list[ChannelSpec],
    *,
    document_mode_default: str = "thread",
    past_days: int = 90,
) -> tuple[SlackHarvesterPlugin, AsyncMock]:
    cfg = SlackConfig(
        channels=channels,
        document_mode_default=document_mode_default,
        past_days=past_days,
    )
    mock_client = AsyncMock(spec=SlackClient)
    plugin = SlackHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


# ── Scaffold ──────────────────────────────────────────────────────


def test_plugin_is_a_sourceplugin():
    plugin, _ = _make_plugin([ChannelSpec(id="C1")])
    assert isinstance(plugin, SourcePlugin)


def test_factory_registered():
    assert "slack" in registered_source_types()


def test_factory_raises_without_token(monkeypatch):
    monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="Slack token not found"):
        create_plugin("slack", {"channels": [{"id": "C1"}]})


def test_factory_normalises_string_channel_entries(monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-test")
    plugin, _client = create_plugin("slack", {"channels": ["C1", {"id": "C2", "mode": "both"}]})
    assert [c.id for c in plugin.config.channels] == ["C1", "C2"]
    assert plugin.config.channels[1].mode == "both"


# ── test_connection ────────────────────────────────────────────────


async def test_test_connection_healthy():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.auth_test.return_value = {"team": "Acme", "user": "alice"}
    mock.users_list.return_value = {"members": [], "response_metadata": {"next_cursor": ""}}
    status = await plugin.test_connection()
    assert isinstance(status, HealthStatus)
    assert status.healthy is True
    assert "alice" in status.message and "Acme" in status.message


async def test_test_connection_translates_auth_error_to_remediation():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.auth_test.side_effect = SlackAuthError("invalid_auth", slack_error="invalid_auth")
    status = await plugin.test_connection()
    assert status.healthy is False
    assert "SLACK_USER_TOKEN" in status.message


# ── list_documents ────────────────────────────────────────────────


async def test_list_documents_thread_mode_emits_one_per_thread_starter():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")], document_mode_default="thread")
    mock.conversations_info.return_value = {"id": "C1", "name": "general"}
    mock.conversations_history.return_value = {
        "messages": [
            {"ts": "1.0", "user": "U1", "text": "topic A"},
            {"ts": "2.0", "user": "U2", "text": "topic B"},
        ],
        "has_more": False,
    }
    refs = await plugin.list_documents()
    assert [r.source_id for r in refs] == [
        "slack:C1:thread:1.0",
        "slack:C1:thread:2.0",
    ]
    assert all(r.metadata["document_type"] == "thread" for r in refs)


async def test_list_documents_summary_mode_emits_one_per_active_day():
    plugin, mock = _make_plugin(
        [ChannelSpec(id="C1")], document_mode_default="channel_summary",
    )
    mock.conversations_info.return_value = {"id": "C1", "name": "standups"}
    # Two messages in two different days
    mock.conversations_history.return_value = {
        "messages": [
            {"ts": "1778630400.0001"},  # 2026-05-13 00:00 UTC
            {"ts": "1778716800.0001"},  # 2026-05-14 00:00 UTC
        ],
        "has_more": False,
    }
    refs = await plugin.list_documents()
    assert {r.source_id for r in refs} == {
        "slack:C1:summary:2026-05-13",
        "slack:C1:summary:2026-05-14",
    }
    assert all(r.metadata["document_type"] == "channel_summary" for r in refs)


async def test_list_documents_both_mode_emits_both_kinds_without_collision():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")], document_mode_default="both")
    mock.conversations_info.return_value = {"id": "C1", "name": "general"}
    mock.conversations_history.return_value = {
        "messages": [{"ts": "1778630400.0001", "user": "U1"}],
        "has_more": False,
    }
    refs = await plugin.list_documents()
    source_ids = {r.source_id for r in refs}
    # Exactly one thread + one summary; namespaces are distinct.
    assert any(":thread:" in s for s in source_ids)
    assert any(":summary:" in s for s in source_ids)
    assert len(refs) == 2


async def test_per_channel_mode_override_wins_over_default():
    plugin, mock = _make_plugin(
        [ChannelSpec(id="C1", mode="channel_summary")],
        document_mode_default="thread",  # default would be thread
    )
    mock.conversations_info.return_value = {"id": "C1", "name": "x"}
    mock.conversations_history.return_value = {
        "messages": [{"ts": "1778630400.0001"}],
        "has_more": False,
    }
    refs = await plugin.list_documents()
    assert all(":summary:" in r.source_id for r in refs)


# ── fetch_document ────────────────────────────────────────────────


async def test_fetch_document_thread_returns_json_envelope_and_attachments():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.conversations_info.return_value = {"id": "C1", "name": "general"}
    mock.conversations_replies.return_value = {
        "messages": [
            {"ts": "1.0", "user": "U1", "text": "hi", "files": [
                {"id": "F1", "name": "x.pdf", "url_private": "https://files.slack.com/x"},
                {"id": "F2", "name": "y.pdf", "mode": "tombstone"},  # excluded
            ]}
        ],
        "has_more": False,
    }
    doc_ref = DocRef(
        source_id="slack:C1:thread:1.0",
        title="x",
        source_type="slack",
        modified_at=datetime.now(tz=timezone.utc),
        metadata={"document_type": "thread", "channel_id": "C1", "thread_ts": "1.0"},
    )
    raw = await plugin.fetch_document(doc_ref)
    assert isinstance(raw, RawDocument)
    assert raw.format == "json"
    envelope = json.loads(raw.content.decode())
    assert envelope["channel"]["id"] == "C1"
    assert len(envelope["messages"]) == 1
    assert len(raw.attachments) == 1  # tombstone excluded
    assert raw.attachments[0].filename == "x.pdf"
    assert raw.metadata["document_type"] == "thread"


async def test_fetch_attachment_delegates_to_client_download():
    plugin, mock = _make_plugin([ChannelSpec(id="C1")])
    mock.download_file.return_value = b"binary content"
    att = AttachmentRef(source_id="x", filename="x.pdf", url="https://files.slack.com/x")
    out = await plugin.fetch_attachment(att)
    assert out == b"binary content"
    mock.download_file.assert_awaited_once_with("https://files.slack.com/x")


# ── normalize ────────────────────────────────────────────────────


def test_normalize_dispatches_on_document_type():
    plugin, _ = _make_plugin([ChannelSpec(id="C1")])
    envelope = {"channel": {"id": "C1", "name": "general"}, "messages": [
        {"ts": "1.0", "user": "U1", "text": "hi"},
    ]}
    raw = RawDocument(
        source_id="slack:C1:thread:1.0",
        title="x",
        content=json.dumps(envelope).encode(),
        format="json",
        metadata={"document_type": "thread", "channel_name": "#general",
                  "resolved_mentions": {"U1": "@alice"}},
    )
    out = plugin.normalize(raw)
    assert isinstance(out, NormalizedDocument)
    assert "@alice" in out.markdown
    assert out.frontmatter == {}
