"""Unit tests for :mod:`src.harvester.gmail.mime`.

Covers the part-walking, base64url decoding, charset handling, and the
plain-vs-html selection logic that drives every Gmail body conversion.
"""

from __future__ import annotations

import base64

from src.harvester.gmail.mime import (
    extract_text_part,
    mime_to_markdown,
)


# ── Inline payload builders ──────────────────────────────────────


def _b64url(text: str, charset: str = "utf-8") -> str:
    """URL-safe base64 encode *text* (Gmail's ``body.data`` shape)."""
    return base64.urlsafe_b64encode(text.encode(charset)).decode("ascii")


def _part(
    mime_type: str,
    *,
    text: str | None = None,
    charset: str = "utf-8",
    parts: list[dict] | None = None,
    attachment_id: str | None = None,
    filename: str | None = None,
) -> dict:
    """Construct a Gmail MIME part dict."""
    part: dict = {"mimeType": mime_type}
    if text is not None:
        part["body"] = {"data": _b64url(text, charset)}
    if attachment_id is not None:
        part["body"] = {"attachmentId": attachment_id, "size": 1024}
    if filename is not None:
        part["filename"] = filename
    if charset != "utf-8" and text is not None:
        part["headers"] = [
            {"name": "Content-Type", "value": f"{mime_type}; charset={charset}"}
        ]
    if parts is not None:
        part["parts"] = parts
    return part


# ── extract_text_part ───────────────────────────────────────────


def test_extract_prefers_plaintext_over_html():
    payload = _part(
        "multipart/alternative",
        parts=[
            _part("text/plain", text="hello plain"),
            _part("text/html", text="<p>hello html</p>"),
        ],
    )
    mime, body = extract_text_part(payload)
    assert mime == "text/plain"
    assert body == "hello plain"


def test_extract_falls_back_to_html_when_no_plain():
    payload = _part(
        "multipart/related",
        parts=[
            _part("text/html", text="<p>only html</p>"),
            _part("image/png", attachment_id="att-1", filename="logo.png"),
        ],
    )
    mime, body = extract_text_part(payload)
    assert mime == "text/html"
    assert body == "<p>only html</p>"


def test_extract_handles_single_part_message():
    """Single-part text/plain at the root: no ``parts`` list."""
    payload = _part("text/plain", text="single body")
    mime, body = extract_text_part(payload)
    assert mime == "text/plain"
    assert body == "single body"


def test_extract_returns_empty_when_no_text_parts():
    payload = _part(
        "multipart/mixed",
        parts=[_part("image/png", attachment_id="a", filename="x.png")],
    )
    mime, body = extract_text_part(payload)
    assert mime == ""
    assert body == ""


def test_extract_decodes_non_utf8_charset():
    """A part declaring iso-8859-1 charset is decoded with that codec."""
    text = "café"
    payload = _part(
        "text/plain",
        text=text,
        charset="iso-8859-1",
    )
    mime, body = extract_text_part(payload)
    assert mime == "text/plain"
    assert body == text


def test_extract_walks_nested_multipart():
    """plaintext nested two levels deep is still picked up."""
    payload = _part(
        "multipart/mixed",
        parts=[
            _part(
                "multipart/alternative",
                parts=[_part("text/plain", text="deep plain")],
            ),
        ],
    )
    mime, body = extract_text_part(payload)
    assert mime == "text/plain"
    assert body == "deep plain"


# ── mime_to_markdown ────────────────────────────────────────────


def test_markdown_passes_plaintext_unchanged():
    payload = _part("text/plain", text="line one\nline two")
    assert mime_to_markdown(payload) == "line one\nline two"


def test_markdown_converts_html_to_markdown():
    payload = _part("text/html", text="<h1>Title</h1><p>body</p>")
    out = mime_to_markdown(payload)
    # markdownify with ATX headings produces "# Title"
    assert "# Title" in out
    assert "body" in out


def test_markdown_appends_attachment_placeholders():
    payload = _part(
        "multipart/mixed",
        parts=[
            _part("text/plain", text="see attachment"),
            _part("application/pdf", attachment_id="a-1", filename="report.pdf"),
        ],
    )
    out = mime_to_markdown(payload)
    assert "see attachment" in out
    assert "[attachment: report.pdf]" in out


def test_markdown_handles_empty_payload():
    """An empty payload yields an empty string (no exception)."""
    assert mime_to_markdown({}) == ""


def test_markdown_attachment_only_payload_emits_placeholders():
    payload = _part(
        "multipart/mixed",
        parts=[_part("application/pdf", attachment_id="a-1", filename="x.pdf")],
    )
    out = mime_to_markdown(payload)
    assert out == "[attachment: x.pdf]"
