"""Gmail thread JSON → clean markdown body.

Public API: ``gmail_to_markdown(raw_content, metadata) -> str``.

The output is **pure markdown body** — no YAML frontmatter, no metadata
headers — to match the contract documented on
:class:`src.harvester.NormalizedDocument`. All structured metadata
(subject, from, to, labels, timestamps, URL, attachment count) lives in
the harvest manifest's ``documents.metadata`` JSON column instead, where
the orchestrator persists it from :attr:`RawDocument.metadata`.

Mirror of :mod:`src.harvester.confluence.normalizer`. Compare to
:mod:`src.harvester.jira.normalizer`, which embeds frontmatter at the
top of its output (a contract-violator we explicitly do not extend).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from email.utils import getaddresses

from .mime import mime_to_markdown

logger = logging.getLogger(__name__)

_EXCESSIVE_BLANKS = re.compile(r"\n{3,}")


def _extract_header(headers: list[dict], name: str) -> str:
    """Return the first matching header value (case-insensitive), or ``""``."""
    target = name.lower()
    for h in headers or ():
        if (h.get("name") or "").lower() == target:
            return h.get("value") or ""
    return ""


def _format_message_date(internal_date: str | int | None) -> str:
    """Render ``internalDate`` as ``YYYY-MM-DD HH:MM`` UTC.

    Gmail returns ``internalDate`` as a string of milliseconds since
    epoch. Times are rendered in UTC for stability across machines —
    a reader on any timezone sees the same ordering.
    """
    if internal_date is None:
        return ""
    try:
        ms = int(internal_date)
    except (TypeError, ValueError):
        return ""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_sender(from_value: str) -> str:
    """Render a ``From`` header value as ``Display Name <email@addr>``.

    Falls back to whichever component is present. Bare addresses render
    as ``email@addr`` (no angle brackets); display-name-only values
    (which shouldn't occur in practice but defend against malformed
    headers) render as just the name.
    """
    if not from_value:
        return ""
    pairs = getaddresses([from_value])
    if not pairs:
        return from_value.strip()
    name, addr = pairs[0]
    if name and addr:
        return f"{name} <{addr}>"
    return name or addr or from_value.strip()


def gmail_to_markdown(raw_content: bytes, metadata: dict) -> str:
    """Convert a raw Gmail thread JSON payload to pure-body markdown.

    Output structure:

        # <subject>

        ## YYYY-MM-DD HH:MM — Display Name <email@addr>

        <message body, markdown>

        ## YYYY-MM-DD HH:MM — Other Sender <other@addr>

        <message body, markdown>

    Empty subject falls back to ``# (no subject)``. Messages are sorted
    ascending by ``internalDate`` so the earliest message is at the top
    — natural reading order for a conversation thread.

    The ``metadata`` dict (typically the output of
    :func:`flatten_thread_fields`) is consulted only as a fallback for
    the subject heading; everything else comes from the JSON itself so
    a downstream re-normalisation (``mnemify normalize --force``)
    produces the same output regardless of whether the manifest is
    available.
    """
    try:
        thread = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.exception("Gmail thread JSON parse failed")
        return "<!-- normalization failed: could not parse thread JSON -->\n"

    messages = thread.get("messages") or []
    sorted_msgs = sorted(messages, key=lambda m: int(m.get("internalDate") or 0))

    # Subject — prefer the latest message's header (matches what the user
    # would see in the Gmail UI), fall back to metadata, then to a placeholder.
    subject = ""
    if sorted_msgs:
        latest_headers = (sorted_msgs[-1].get("payload") or {}).get("headers") or []
        subject = _extract_header(latest_headers, "Subject")
    if not subject:
        subject = (metadata or {}).get("subject", "") or ""
    if not subject:
        subject = "(no subject)"

    parts: list[str] = [f"# {subject}", ""]

    for msg in sorted_msgs:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        date_str = _format_message_date(msg.get("internalDate"))
        sender = _format_sender(_extract_header(headers, "From"))

        # Heading — guard against the edge case where both date and
        # sender are unparseable; fall back to the message ID rather than
        # producing an empty heading.
        if date_str and sender:
            heading = f"## {date_str} — {sender}"
        elif date_str:
            heading = f"## {date_str}"
        elif sender:
            heading = f"## {sender}"
        else:
            heading = f"## (message {msg.get('id', '?')})"

        body = mime_to_markdown(payload).strip()
        parts.append(heading)
        parts.append("")
        if body:
            parts.append(body)
        else:
            parts.append("(no content)")
        parts.append("")

    output = "\n".join(parts)
    output = _EXCESSIVE_BLANKS.sub("\n\n", output)
    return f"{output.strip()}\n"
