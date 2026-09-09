"""Tests for the Slack normalizer's pure-function mention/link/reaction rendering."""

from __future__ import annotations

import json

from src.harvester.slack.normalizer import (
    _resolve_mentions,
    slack_summary_to_markdown,
    slack_thread_to_markdown,
)


# ── _resolve_mentions ─────────────────────────────────────────────


def test_user_mention_resolved_from_snapshot():
    snap = {"U0123": "@alice"}
    assert _resolve_mentions("hello <@U0123> there", snap) == "hello @alice there"


def test_user_mention_falls_back_to_raw_id_when_unknown():
    out = _resolve_mentions("ping <@U0999>", {})
    assert "@U0999" in out


def test_channel_mention_uses_inline_name_when_present():
    out = _resolve_mentions("see <#C0123|general> notes", {})
    assert out == "see #general notes"


def test_channel_mention_falls_back_to_snapshot_then_id():
    snap = {"C0456": "#design"}
    assert _resolve_mentions("ping <#C0456>", snap) == "ping #design"
    assert "#C0999" in _resolve_mentions("ping <#C0999>", {})


def test_special_mentions_here_channel():
    assert "@here" in _resolve_mentions("<!here>", {})
    assert "@channel" in _resolve_mentions("<!channel>", {})


def test_subteam_mention_uses_label():
    out = _resolve_mentions("<!subteam^S01|@oncall> ping", {})
    assert "@@oncall" in out or "@oncall" in out


def test_link_label_rendered_as_markdown():
    out = _resolve_mentions("see <https://example.com|the doc> later", {})
    assert out == "see [the doc](https://example.com) later"


def test_bare_link_kept():
    assert _resolve_mentions("read <https://example.com>", {}) == "read [https://example.com](https://example.com)"


def test_specials_unescaped():
    assert _resolve_mentions("a &amp; b &lt;c&gt;", {}) == "a & b <c>"


# ── slack_thread_to_markdown ──────────────────────────────────────


def _thread_envelope(messages: list[dict]) -> bytes:
    return json.dumps({"channel": {"id": "C1", "name": "general"}, "messages": messages}).encode()


def test_thread_renders_root_with_author_heading():
    msgs = [
        {"ts": "1700000000.000100", "user": "U1", "text": "hello world"},
        {"ts": "1700000060.000200", "user": "U2", "text": "reply text"},
    ]
    md = slack_thread_to_markdown(
        _thread_envelope(msgs),
        {
            "channel_name": "#general",
            "resolved_mentions": {"U1": "@alice", "U2": "@bob"},
        },
    )
    assert "@alice in #general: hello world" in md
    assert "## " in md  # at least one message heading
    assert "@bob" in md
    assert "reply text" in md


def test_thread_reaction_only_root_renders_reactions_as_body():
    msgs = [
        {"ts": "1700000000.0001", "user": "U1", "text": "", "reactions": [{"name": "rocket", "count": 3}]}
    ]
    md = slack_thread_to_markdown(
        _thread_envelope(msgs),
        {"channel_name": "#general", "resolved_mentions": {"U1": "@alice"}},
    )
    assert ":rocket:" in md
    # No "(empty message)" placeholder when reactions filled the body.
    assert "(empty message)" not in md


def test_thread_tombstoned_file_renders_removed_marker():
    msgs = [
        {"ts": "1700000000.0001", "user": "U1", "text": "see file",
         "files": [{"id": "F1", "name": "x.pdf", "mode": "tombstone"}]}
    ]
    md = slack_thread_to_markdown(
        _thread_envelope(msgs),
        {"channel_name": "#general", "resolved_mentions": {"U1": "@alice"}},
    )
    assert "[file removed]" in md


def test_thread_attachment_renders_as_attachment_link():
    msgs = [
        {"ts": "1700000000.0001", "user": "U1", "text": "doc",
         "files": [{"id": "F77", "name": "spec.pdf", "url_private": "https://files.slack.com/x"}]}
    ]
    md = slack_thread_to_markdown(
        _thread_envelope(msgs),
        {"channel_name": "#general", "resolved_mentions": {"U1": "@alice"}},
    )
    assert "attachment://F77" in md
    assert "spec.pdf" in md


def test_bot_message_uses_username_not_user_field():
    msgs = [
        {"ts": "1700000000.0001", "username": "Deploy Bot", "subtype": "bot_message", "text": "deployed"}
    ]
    md = slack_thread_to_markdown(_thread_envelope(msgs), {"channel_name": "#ci", "resolved_mentions": {}})
    assert "Deploy Bot" in md


# ── slack_summary_to_markdown ─────────────────────────────────────


def _summary_envelope(messages: list[dict], day: str = "2026-05-13") -> bytes:
    return json.dumps({"channel": {"id": "C1", "name": "standups"}, "day": day, "messages": messages}).encode()


def test_summary_header_includes_counts():
    msgs = [
        {"ts": "1700000000.0001", "user": "U1", "text": "status today"},
        {"ts": "1700000060.0002", "user": "U2", "text": "blocked on X"},
        {"ts": "1700000120.0003", "user": "U1", "text": "done", "thread_ts": "1700000000.0001"},
    ]
    md = slack_summary_to_markdown(
        _summary_envelope(msgs),
        {"channel_name": "#standups", "resolved_mentions": {"U1": "@alice", "U2": "@bob"}, "participant_count": 2},
    )
    assert "2026-05-13" in md
    assert "3 messages" in md
    assert "2 people" in md


def test_summary_groups_replies_under_parent():
    msgs = [
        {"ts": "1700000000.0001", "user": "U1", "text": "topic"},
        {"ts": "1700000060.0002", "user": "U2", "text": "reply", "thread_ts": "1700000000.0001"},
    ]
    md = slack_summary_to_markdown(
        _summary_envelope(msgs),
        {"channel_name": "#general", "resolved_mentions": {"U1": "@alice", "U2": "@bob"}, "participant_count": 2},
    )
    # Reply bullet indented under parent
    lines = md.splitlines()
    parent_idx = next(i for i, line in enumerate(lines) if "@alice" in line)
    reply_idx = next(i for i, line in enumerate(lines) if "@bob" in line)
    assert reply_idx > parent_idx
    assert lines[reply_idx].startswith("  - ")  # indented
