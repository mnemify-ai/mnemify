"""Tests for src.harvester.slack.fields flatteners."""

from __future__ import annotations

import pytest

# Slack is not enabled in this build, so `slack-sdk` moved to the optional
# `slack` extra (see pyproject.toml + src/sources.py). The plugin code under
# test imports it at module level, so skip the file rather than fail
# collection on a default install. `uv sync --extra all-sources` runs these.
pytest.importorskip("slack_sdk")

from src.harvester.slack.fields import (
    flatten_summary_fields,
    flatten_thread_fields,
)


# ── flatten_thread_fields ─────────────────────────────────────────


def test_flatten_thread_basic_shape():
    channel = {"id": "C1", "name": "general"}
    root = {"ts": "1700000000.0001", "user": "U1", "text": "hello world"}
    replies = [
        root,
        {"ts": "1700000060.0001", "user": "U2", "text": "reply"},
        {"ts": "1700000120.0001", "user": "U3", "text": "another"},
    ]
    snap = {"U1": "@alice", "U2": "@bob", "U3": "@carol"}
    out = flatten_thread_fields(
        channel=channel, root=root, replies=replies, name_snapshot=snap,
    )
    assert out["document_type"] == "thread"
    assert out["channel_id"] == "C1"
    assert out["thread_ts"] == root["ts"]
    assert out["reply_count"] == 2
    assert out["participant_count"] == 3
    assert {p["name"] for p in out["participants"]} == {"@alice", "@bob", "@carol"}
    assert out["root_author_name"] == "@alice"


def test_flatten_thread_is_dm_for_D_channel():
    channel = {"id": "D0123", "is_im": True}
    root = {"ts": "1700000000.0001", "user": "U1", "text": "hi"}
    out = flatten_thread_fields(channel=channel, root=root, replies=[root], name_snapshot={"U1": "@alice"})
    assert out["is_dm"] is True
    assert out["channel_name"] == "(direct message)"


def test_flatten_thread_reaction_only_root_has_nonempty_preview():
    channel = {"id": "C1", "name": "general"}
    root = {"ts": "1700000000.0001", "user": "U1", "text": "",
            "reactions": [{"name": "rocket", "count": 1}]}
    out = flatten_thread_fields(channel=channel, root=root, replies=[root], name_snapshot={"U1": "@alice"})
    assert out["root_text_preview"] != ""
    assert "rocket" in out["root_text_preview"]


def test_flatten_thread_reaction_summary_counts_across_messages():
    channel = {"id": "C1", "name": "general"}
    root = {"ts": "1.0", "user": "U1", "text": "hi",
            "reactions": [{"name": "thumbsup", "count": 2}]}
    replies = [
        root,
        {"ts": "2.0", "user": "U2", "text": "yep",
         "reactions": [{"name": "thumbsup", "count": 1}, {"name": "rocket", "count": 3}]},
    ]
    out = flatten_thread_fields(channel=channel, root=root, replies=replies, name_snapshot={})
    assert out["reaction_summary"] == {"thumbsup": 3, "rocket": 3}


def test_flatten_thread_attachment_count_excludes_tombstones():
    channel = {"id": "C1", "name": "general"}
    root = {"ts": "1.0", "user": "U1", "text": "see files", "files": [
        {"id": "F1", "name": "x.pdf"},
        {"id": "F2", "name": "y.pdf", "mode": "tombstone"},
    ]}
    out = flatten_thread_fields(channel=channel, root=root, replies=[root], name_snapshot={})
    assert out["attachment_count"] == 1


def test_flatten_thread_archived_channel_marked_in_name():
    channel = {"id": "C1", "name": "old-stuff", "is_archived": True}
    root = {"ts": "1.0", "user": "U1", "text": "x"}
    out = flatten_thread_fields(channel=channel, root=root, replies=[root], name_snapshot={})
    assert out["is_archived"] is True
    assert "archived" in out["channel_name"]


# ── flatten_summary_fields ────────────────────────────────────────


def test_flatten_summary_carries_references():
    channel = {"id": "C1", "name": "general"}
    msgs = [
        {"ts": "1.0", "user": "U1", "text": "topic A"},
        {"ts": "2.0", "user": "U2", "text": "topic B"},
    ]
    refs = ["slack:C1:thread:1.0", "slack:C1:thread:2.0"]
    out = flatten_summary_fields(
        channel=channel, day_iso="2026-05-13", messages=msgs,
        references=refs, name_snapshot={"U1": "@alice", "U2": "@bob"},
    )
    assert out["document_type"] == "channel_summary"
    assert out["summary_day"] == "2026-05-13"
    assert out["message_count"] == 2
    assert out["participant_count"] == 2
    assert out["references"] == refs
