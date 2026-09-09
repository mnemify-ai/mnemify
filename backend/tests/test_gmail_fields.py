"""Unit tests for :func:`src.harvester.gmail.fields.flatten_thread_fields`.

The flatten function is the single place where Gmail's thread JSON is
projected into the manifest's ``documents.metadata`` JSON column. Header
extraction, address-list parsing, label union, and ``internalDate`` →
RFC3339 conversion all live here, so they all get pinned tests.
"""

from __future__ import annotations

from src.harvester.gmail.fields import flatten_thread_fields


# ── Inline thread builders ───────────────────────────────────────


def _msg(
    *,
    msg_id: str = "m1",
    internal_date_ms: int = 1745520000000,  # 2025-04-24 18:40 UTC
    subject: str = "",
    from_h: str = "",
    to_h: str = "",
    cc_h: str = "",
    label_ids: list[str] | None = None,
    attachments: int = 0,
) -> dict:
    headers: list[dict] = []
    if subject:
        headers.append({"name": "Subject", "value": subject})
    if from_h:
        headers.append({"name": "From", "value": from_h})
    if to_h:
        headers.append({"name": "To", "value": to_h})
    if cc_h:
        headers.append({"name": "Cc", "value": cc_h})

    parts = []
    for i in range(attachments):
        parts.append(
            {
                "mimeType": "application/pdf",
                "filename": f"doc-{i}.pdf",
                "body": {"attachmentId": f"att-{msg_id}-{i}", "size": 100},
            }
        )

    payload = {"headers": headers}
    if parts:
        payload["mimeType"] = "multipart/mixed"
        payload["parts"] = parts

    return {
        "id": msg_id,
        "internalDate": str(internal_date_ms),
        "labelIds": label_ids or [],
        "payload": payload,
    }


def _thread(thread_id: str = "t1", *messages: dict, snippet: str = "") -> dict:
    return {
        "id": thread_id,
        "historyId": "hist-99",
        "snippet": snippet,
        "messages": list(messages),
    }


# ── Subject / From — taken from latest message ────────────────────


def test_subject_from_latest_message():
    """Subject comes from the most recent message's ``Subject`` header."""
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, subject="Original"),
            _msg(internal_date_ms=2, subject="Re: Original"),
        )
    )
    assert out["subject"] == "Re: Original"


def test_from_addr_and_name_from_latest_message():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, from_h="Amy Chen <amy@acme.com>"),
            _msg(internal_date_ms=2, from_h="Sarah <sarah@tensor.io>"),
        )
    )
    assert out["from_addr"] == "sarah@tensor.io"
    assert out["from_name"] == "Sarah"


def test_from_handles_bare_address():
    out = flatten_thread_fields(
        _thread("t1", _msg(from_h="amy@acme.com"))
    )
    assert out["from_addr"] == "amy@acme.com"
    assert out["from_name"] == ""


# ── To / Cc — union across messages ───────────────────────────────


def test_to_addrs_union_across_messages_dedupe_first_seen_order():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, to_h="a@x.com, b@x.com"),
            _msg(internal_date_ms=2, to_h="b@x.com, c@x.com"),
        )
    )
    assert out["to_addrs"] == ["a@x.com", "b@x.com", "c@x.com"]


def test_cc_addrs_union_across_messages():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, cc_h="cc1@x.com"),
            _msg(internal_date_ms=2, cc_h="cc2@x.com"),
        )
    )
    assert out["cc_addrs"] == ["cc1@x.com", "cc2@x.com"]


# ── Labels — union across messages ───────────────────────────────


def test_label_union_across_messages_first_seen_order():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, label_ids=["INBOX", "IMPORTANT"]),
            _msg(internal_date_ms=2, label_ids=["IMPORTANT", "Acme/Renewal"]),
        )
    )
    assert out["labels"] == ["INBOX", "IMPORTANT", "Acme/Renewal"]


# ── internalDate → RFC3339 UTC ───────────────────────────────────


def test_first_and_last_message_at_in_rfc3339_utc():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1745520000000),  # 2025-04-24 18:40 UTC
            _msg(internal_date_ms=1745606400000),  # 2025-04-25 18:40 UTC
        )
    )
    assert out["first_message_at"] == "2025-04-24T18:40:00Z"
    assert out["last_message_at"] == "2025-04-25T18:40:00Z"


def test_internal_date_missing_yields_empty_string():
    """A message with no ``internalDate`` doesn't crash; produces ''."""
    msg = _msg()
    msg.pop("internalDate")
    out = flatten_thread_fields(_thread("t1", msg))
    assert out["first_message_at"] == ""
    assert out["last_message_at"] == ""


# ── Counts and identifiers ───────────────────────────────────────


def test_message_count():
    out = flatten_thread_fields(
        _thread("t1", _msg(internal_date_ms=1), _msg(internal_date_ms=2), _msg(internal_date_ms=3))
    )
    assert out["message_count"] == 3


def test_attachment_count_walks_all_messages():
    out = flatten_thread_fields(
        _thread(
            "t1",
            _msg(internal_date_ms=1, attachments=2),
            _msg(internal_date_ms=2, attachments=1),
        )
    )
    assert out["attachment_count"] == 3


def test_thread_id_history_id_url_and_snippet():
    out = flatten_thread_fields(
        _thread("18a3f7c2", _msg(), snippet="hi there")
    )
    assert out["thread_id"] == "18a3f7c2"
    assert out["history_id"] == "hist-99"
    assert out["snippet"] == "hi there"
    assert out["url"] == "https://mail.google.com/mail/u/0/#inbox/18a3f7c2"


def test_document_type_is_thread():
    out = flatten_thread_fields(_thread("t1", _msg()))
    assert out["document_type"] == "thread"


# ── Defensive paths ──────────────────────────────────────────────


def test_empty_thread_does_not_crash():
    out = flatten_thread_fields({"id": "t1", "messages": []})
    assert out["message_count"] == 0
    assert out["subject"] == ""
    assert out["to_addrs"] == []
    assert out["labels"] == []
