"""Gmail thread JSON → flat metadata dict.

Analogue of :func:`src.harvester.jira.fields.flatten_issue_fields`. The
plugin keeps the full thread JSON in :class:`RawDocument.content` and
uses this flat dict only for filter / manifest / compiler metadata, so
this projection is **non-lossy** in the same sense — body content is
never dropped here, only summarised.

Headers are case-insensitive in the RFC, so :func:`_extract_header`
performs a lower-case lookup. ``Date`` headers are not authoritative
for ordering across messages — Gmail's ``internalDate`` (ms since epoch
as a string) is what we use for that — so we surface both.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# RFC 5322 address-list parsing is fiddly. The standard library's
# ``email.utils.getaddresses`` handles the corner cases (quoted display
# names, group syntax, comments) better than anything we'd hand-roll.
from email.utils import getaddresses

_THREAD_URL_TEMPLATE = "https://mail.google.com/mail/u/0/#inbox/{thread_id}"


def _extract_header(headers: list[dict], name: str) -> str:
    """Return the first matching header value, or ``""`` if absent.

    Gmail's ``payload.headers`` is a list of ``{name, value}`` dicts; the
    name comparison is case-insensitive per RFC 5322.
    """
    target = name.lower()
    for h in headers or ():
        if (h.get("name") or "").lower() == target:
            return h.get("value") or ""
    return ""


def _parse_addresses(header_value: str) -> list[tuple[str, str]]:
    """Parse an RFC 5322 address-list header into ``[(name, email), ...]``.

    Empty / missing values yield ``[]``. Garbage values yield whatever
    :func:`email.utils.getaddresses` produces — typically a best-effort
    parse rather than a raise.
    """
    if not header_value:
        return []
    pairs = getaddresses([header_value])
    return [(name or "", addr or "") for (name, addr) in pairs if (name or addr)]


def _addresses(header_value: str) -> list[str]:
    """Email-address-only projection of :func:`_parse_addresses`."""
    return [addr for (_name, addr) in _parse_addresses(header_value) if addr]


def _internal_date_to_iso(internal_date: str | int | None) -> str:
    """Convert Gmail's ``internalDate`` (ms since epoch) to RFC3339 UTC.

    Gmail returns ``internalDate`` as a string of milliseconds since
    epoch (``"1745520000000"``), but some test fixtures use ints — accept
    both. Returns an empty string when the input is missing or invalid.
    """
    if internal_date is None:
        return ""
    try:
        ms = int(internal_date)
    except (TypeError, ValueError):
        return ""
    seconds = ms / 1000.0
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    # ISO-8601 with seconds precision; "Z" suffix per RFC3339 convention.
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _count_attachments(messages: list[dict]) -> int:
    count = 0
    for msg in messages or ():
        payload = msg.get("payload") or {}
        for part in _walk_parts(payload):
            body = part.get("body") or {}
            if body.get("attachmentId"):
                count += 1
    return count


def _walk_parts(payload: dict):
    """Depth-first traversal yielding every part in a MIME tree.

    The root payload itself is yielded first (covers single-part
    messages where ``parts`` is absent), then each nested part
    recursively.
    """
    if not payload:
        return
    yield payload
    for part in payload.get("parts") or ():
        yield from _walk_parts(part)


def flatten_thread_fields(thread: dict) -> dict:
    """Project a raw Gmail thread JSON into the flat metadata dict.

    Output keys:

    - ``document_type``: always ``"thread"``.
    - ``subject``: from the latest message's ``Subject`` header.
    - ``from_addr`` / ``from_name``: latest message's parsed ``From``.
    - ``to_addrs`` / ``cc_addrs``: union of addresses across all messages.
    - ``labels``: union of message-level ``labelIds`` across the thread.
    - ``message_count``: ``len(messages)``.
    - ``first_message_at`` / ``last_message_at``: RFC3339 UTC strings
      derived from ``internalDate`` of the first / last message.
    - ``snippet``: the thread-level ``snippet`` (Gmail's preview text).
    - ``thread_id`` / ``history_id``: identifiers from the envelope.
    - ``url``: deep-link to the thread in the Gmail web UI.
    - ``attachment_count``: number of payload parts with an
      ``attachmentId`` across all messages in the thread.

    Defensive throughout — every ``or {}`` / ``or []`` / explicit length
    check is there because Gmail occasionally returns ``null`` for
    expected sub-objects on edge cases (e.g. drafts saved without a
    body).
    """
    messages = thread.get("messages") or []

    # Sort messages chronologically so "first" and "latest" are stable.
    # Gmail does return them in chronological order in practice, but the
    # API contract doesn't guarantee it.
    sorted_msgs = sorted(messages, key=lambda m: int(m.get("internalDate") or 0))

    first_msg = sorted_msgs[0] if sorted_msgs else {}
    latest_msg = sorted_msgs[-1] if sorted_msgs else {}

    latest_headers = (latest_msg.get("payload") or {}).get("headers") or []
    subject = _extract_header(latest_headers, "Subject")

    from_pairs = _parse_addresses(_extract_header(latest_headers, "From"))
    from_name, from_addr = (from_pairs[0] if from_pairs else ("", ""))

    # Union to/cc addresses across every message in the thread so the
    # manifest captures the full participant set, not just the latest
    # message's recipients.
    to_set: list[str] = []
    cc_set: list[str] = []
    seen_to: set[str] = set()
    seen_cc: set[str] = set()
    for msg in sorted_msgs:
        headers = (msg.get("payload") or {}).get("headers") or []
        for addr in _addresses(_extract_header(headers, "To")):
            if addr not in seen_to:
                seen_to.add(addr)
                to_set.append(addr)
        for addr in _addresses(_extract_header(headers, "Cc")):
            if addr not in seen_cc:
                seen_cc.add(addr)
                cc_set.append(addr)

    # Union of label IDs across every message in the thread; preserves
    # first-seen order for stable manifest diffs.
    labels: list[str] = []
    seen_labels: set[str] = set()
    for msg in sorted_msgs:
        for label in msg.get("labelIds") or ():
            if label not in seen_labels:
                seen_labels.add(label)
                labels.append(label)

    thread_id = thread.get("id") or ""

    return {
        "document_type": "thread",
        "subject": subject,
        "from_addr": from_addr,
        "from_name": from_name,
        "to_addrs": to_set,
        "cc_addrs": cc_set,
        "labels": labels,
        "message_count": len(sorted_msgs),
        "first_message_at": _internal_date_to_iso(first_msg.get("internalDate")),
        "last_message_at": _internal_date_to_iso(latest_msg.get("internalDate")),
        "snippet": thread.get("snippet") or "",
        "thread_id": thread_id,
        "history_id": thread.get("historyId") or "",
        "url": _THREAD_URL_TEMPLATE.format(thread_id=thread_id) if thread_id else "",
        "attachment_count": _count_attachments(sorted_msgs),
    }
