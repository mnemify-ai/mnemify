"""End-to-end tests for :func:`src.harvester.gmail.normalizer.gmail_to_markdown`.

The Gmail normaliser produces **pure-body markdown** — no YAML
frontmatter, no metadata headers — because metadata lives in the
manifest's ``documents.metadata`` JSON column instead. The first
asserted property here is exactly that: the output never starts with
``---``. Mirror of the Confluence normaliser contract; deliberate
contrast with the Jira normaliser, which embeds frontmatter.
"""

from __future__ import annotations

import base64
import json

from src.harvester.gmail.normalizer import gmail_to_markdown


# ── Inline thread builders ───────────────────────────────────────


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _msg(
    *,
    msg_id: str = "m1",
    internal_date_ms: int = 1745520000000,
    subject: str = "",
    from_h: str = "",
    plain_body: str | None = None,
    html_body: str | None = None,
) -> dict:
    headers: list[dict] = []
    if subject:
        headers.append({"name": "Subject", "value": subject})
    if from_h:
        headers.append({"name": "From", "value": from_h})

    payload: dict = {"headers": headers}
    if plain_body is not None and html_body is not None:
        payload["mimeType"] = "multipart/alternative"
        payload["parts"] = [
            {"mimeType": "text/plain", "body": {"data": _b64url(plain_body)}},
            {"mimeType": "text/html", "body": {"data": _b64url(html_body)}},
        ]
    elif plain_body is not None:
        payload["mimeType"] = "text/plain"
        payload["body"] = {"data": _b64url(plain_body)}
    elif html_body is not None:
        payload["mimeType"] = "text/html"
        payload["body"] = {"data": _b64url(html_body)}

    return {
        "id": msg_id,
        "internalDate": str(internal_date_ms),
        "payload": payload,
    }


def _thread(thread_id: str, *messages: dict) -> bytes:
    payload = {"id": thread_id, "messages": list(messages)}
    return json.dumps(payload).encode("utf-8")


# ── Pure-body contract: no YAML frontmatter ──────────────────────


def test_output_does_not_start_with_yaml_delimiter():
    """The Gmail normaliser must NEVER emit a ``---`` frontmatter block."""
    raw = _thread(
        "t1",
        _msg(subject="Hello", from_h="Amy <amy@acme.com>", plain_body="hi"),
    )
    out = gmail_to_markdown(raw, {})
    assert not out.startswith("---")


def test_output_starts_with_subject_heading():
    """First non-empty line should be ``# <subject>``."""
    raw = _thread(
        "t1",
        _msg(subject="Project kickoff", from_h="Amy <amy@acme.com>", plain_body="hi"),
    )
    out = gmail_to_markdown(raw, {})
    first_line = out.lstrip("\n").splitlines()[0]
    assert first_line == "# Project kickoff"


def test_empty_subject_falls_back_to_no_subject_marker():
    raw = _thread(
        "t1",
        _msg(from_h="Amy <amy@acme.com>", plain_body="hi"),
    )
    out = gmail_to_markdown(raw, {})
    first_line = out.lstrip("\n").splitlines()[0]
    assert first_line == "# (no subject)"


def test_subject_falls_back_to_metadata_when_header_missing():
    raw = _thread(
        "t1",
        _msg(from_h="Amy <amy@acme.com>", plain_body="hi"),
    )
    out = gmail_to_markdown(raw, {"subject": "From manifest"})
    assert "# From manifest" in out


# ── Per-message section headings ─────────────────────────────────


def test_per_message_heading_uses_date_em_dash_sender_format():
    raw = _thread(
        "t1",
        _msg(
            subject="Hi",
            from_h="Amy Chen <amy@acme.com>",
            internal_date_ms=1745520000000,
            plain_body="body",
        ),
    )
    out = gmail_to_markdown(raw, {})
    # 1745520000000 ms = 2025-04-24 18:40 UTC
    assert "## 2025-04-24 18:40 — Amy Chen <amy@acme.com>" in out


def test_per_message_heading_handles_bare_email():
    raw = _thread(
        "t1",
        _msg(
            subject="Hi",
            from_h="amy@acme.com",
            internal_date_ms=1745520000000,
            plain_body="body",
        ),
    )
    out = gmail_to_markdown(raw, {})
    assert "## 2025-04-24 18:40 — amy@acme.com" in out


# ── Message ordering ─────────────────────────────────────────────


def test_messages_sorted_ascending_by_internal_date():
    raw = _thread(
        "t1",
        _msg(msg_id="m2", internal_date_ms=2_000_000_000_000, subject="Hi", from_h="b@x", plain_body="second"),
        _msg(msg_id="m1", internal_date_ms=1_000_000_000_000, subject="Hi", from_h="a@x", plain_body="first"),
    )
    out = gmail_to_markdown(raw, {})
    first_pos = out.find("first")
    second_pos = out.find("second")
    assert 0 < first_pos < second_pos


# ── HTML body conversion ─────────────────────────────────────────


def test_html_only_message_converted_to_markdown():
    raw = _thread(
        "t1",
        _msg(
            subject="Update",
            from_h="b@x",
            internal_date_ms=1745520000000,
            html_body="<h1>Title</h1><p>paragraph</p>",
        ),
    )
    out = gmail_to_markdown(raw, {})
    assert "Title" in out
    assert "paragraph" in out


def test_plain_part_preferred_over_html_part():
    raw = _thread(
        "t1",
        _msg(
            subject="Update",
            from_h="b@x",
            internal_date_ms=1745520000000,
            plain_body="just plain text",
            html_body="<p>html version</p>",
        ),
    )
    out = gmail_to_markdown(raw, {})
    assert "just plain text" in out


# ── Empty body ───────────────────────────────────────────────────


def test_message_with_no_body_renders_no_content_marker():
    raw = _thread(
        "t1",
        _msg(subject="Empty", from_h="a@x", internal_date_ms=1745520000000),
    )
    out = gmail_to_markdown(raw, {})
    assert "(no content)" in out


# ── Cleanup ──────────────────────────────────────────────────────


def test_excessive_blank_lines_collapsed():
    raw = _thread(
        "t1",
        _msg(
            subject="Hi",
            from_h="a@x",
            internal_date_ms=1745520000000,
            plain_body="line one\n\n\n\nline two",
        ),
    )
    out = gmail_to_markdown(raw, {})
    assert "\n\n\n" not in out


def test_output_ends_with_single_trailing_newline():
    raw = _thread("t1", _msg(subject="Hi", from_h="a@x", plain_body="body"))
    out = gmail_to_markdown(raw, {})
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


# ── Defensive ────────────────────────────────────────────────────


def test_malformed_json_returns_failure_marker():
    out = gmail_to_markdown(b"{not json", {})
    assert "<!-- normalization failed" in out
