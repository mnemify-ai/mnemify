"""Google Calendar event JSON → clean markdown body.

Public API: ``calendar_to_markdown(raw_content, metadata) -> str``.

Pure-body markdown (no YAML frontmatter, no metadata headers) — same
contract as :mod:`src.harvester.gmail.normalizer` and
:mod:`src.harvester.confluence.normalizer`. The structural metadata
that *is* the content of an event (when, where, who) lives inline as
human-readable bold-prefixed lines at the top of the body, not as a
YAML block. Anything queryable lives in the manifest's
``documents.metadata`` column instead.

Output structure::

    # {summary}                                    (or "(cancelled) {summary}")

    **When:** 2026-04-30 14:00 – 15:00 UTC
    **Where:** Conference Room B
    **Conference:** [Google Meet](https://meet.google.com/...)
    **Organizer:** Amy Chen <amy@acme.com>
    **Attendees:**
    - Alice Smith <alice@x.com> — accepted
    - Bob Jones <bob@y.com> — tentative

    ## Description

    {description, HTML→markdown when needed}

    ## Attachments

    - [Q4 doc](https://docs.google.com/...)

Sections with no content are skipped — events without a description
don't render an empty ``## Description`` heading.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import markdownify

logger = logging.getLogger(__name__)

_EXCESSIVE_BLANKS = re.compile(r"\n{3,}")
_HTML_TAG_HINT = re.compile(r"<(p|br|a|div|span|ul|ol|li|h[1-6]|strong|em|b|i)\b", re.I)


def _format_time_range(start: dict | None, end: dict | None) -> str:
    """Render a human-readable time range for the When line.

    Three cases:

    - All-day single day:    ``"2026-04-30 (all day)"``
    - All-day multi-day:     ``"2026-04-30 – 2026-05-02 (all day)"``
    - Timed:                 ``"2026-04-30 14:00 – 15:00 UTC"``
    - Timed across days:     ``"2026-04-30 23:30 UTC – 2026-05-01 00:30 UTC"``

    Times rendered in UTC for stability across machines (matches the
    Gmail normaliser's convention; the manifest carries the raw
    timezoned strings if anyone needs the original).
    """
    start = start or {}
    end = end or {}

    # All-day events use ``date`` (YYYY-MM-DD) without a time component.
    if start.get("date"):
        start_date = start["date"]
        end_date = end.get("date")
        # Calendar's all-day end-date is exclusive ("ends at start of
        # 2026-05-02" means the event runs through 2026-05-01). Surface
        # both forms verbatim — readers expect the start to be inclusive
        # and the rendering says "(all day)" so the meaning is clear.
        if end_date and end_date != start_date:
            return f"{start_date} – {end_date} (all day)"
        return f"{start_date} (all day)"

    start_dt = _parse_calendar_dt(start.get("dateTime"))
    end_dt = _parse_calendar_dt(end.get("dateTime"))

    if start_dt is None and end_dt is None:
        return ""

    if start_dt and end_dt:
        if start_dt.date() == end_dt.date():
            return (
                f"{start_dt.strftime('%Y-%m-%d %H:%M')} – "
                f"{end_dt.strftime('%H:%M')} UTC"
            )
        return (
            f"{start_dt.strftime('%Y-%m-%d %H:%M')} UTC – "
            f"{end_dt.strftime('%Y-%m-%d %H:%M')} UTC"
        )
    if start_dt:
        return f"{start_dt.strftime('%Y-%m-%d %H:%M')} UTC"
    return f"ends {end_dt.strftime('%Y-%m-%d %H:%M')} UTC"  # type: ignore[union-attr]


def _parse_calendar_dt(value: str | None) -> datetime | None:
    """Parse a Calendar ``dateTime`` string and normalise to naive UTC.

    Calendar emits offsets like ``2026-04-30T14:00:00-07:00``. Strip the
    offset by converting to UTC, then drop tzinfo so downstream string
    formatting doesn't add a ``+00:00``.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _format_organizer(organizer: dict | None) -> str:
    """Render the organizer as ``Display Name <email>`` (best-effort)."""
    if not organizer:
        return ""
    name = organizer.get("displayName") or ""
    email = organizer.get("email") or ""
    if name and email:
        return f"{name} <{email}>"
    return name or email


def _format_attendees(attendees: list[dict] | None) -> list[str]:
    """Render each attendee as a markdown list line with response status."""
    out: list[str] = []
    for attendee in attendees or ():
        name = attendee.get("displayName") or ""
        email = attendee.get("email") or ""
        response = attendee.get("responseStatus") or ""
        identity = f"{name} <{email}>" if (name and email) else (name or email)
        if not identity:
            continue
        if response:
            out.append(f"- {identity} — {response}")
        else:
            out.append(f"- {identity}")
    return out


def _format_conference_link(event: dict) -> str:
    """Pull the video conference URL and render it as a markdown link.

    Returns ``""`` when no conference URL is attached.
    """
    conf = event.get("conferenceData") or {}
    name = (conf.get("conferenceSolution") or {}).get("name") or "Conference"
    for entry in conf.get("entryPoints") or ():
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return f"[{name}]({entry['uri']})"
    hangout = event.get("hangoutLink")
    if hangout:
        return f"[{name}]({hangout})"
    return ""


def _render_description(description: str) -> str:
    """Convert a Calendar event description to markdown.

    Calendar lets users author descriptions as either plain text or
    HTML (via the API or via the web UI's rich-text mode). The shape
    isn't tagged in the response, so we sniff for common HTML tags and
    run through ``markdownify`` only when present. Plain text passes
    through unchanged.
    """
    if not description:
        return ""
    if _HTML_TAG_HINT.search(description):
        try:
            return markdownify.markdownify(description, heading_style="ATX").strip()
        except Exception:  # noqa: BLE001 — fall back to raw on conversion failure
            logger.exception("Calendar description HTML→markdown conversion failed")
            return description.strip()
    return description.strip()


def _render_attachments(attachments: list[dict] | None) -> list[str]:
    """Render each attached Drive document as a markdown list line."""
    out: list[str] = []
    for att in attachments or ():
        title = att.get("title") or att.get("fileId") or "(unnamed)"
        url = att.get("fileUrl") or ""
        if url:
            out.append(f"- [{title}]({url})")
        else:
            out.append(f"- {title}")
    return out


def calendar_to_markdown(raw_content: bytes, metadata: dict) -> str:
    """Convert a raw Google Calendar event JSON payload to pure-body markdown.

    The ``metadata`` dict (typically the output of
    :func:`flatten_event_fields`) is consulted only as a fallback for
    the summary heading; everything else comes from the JSON itself so
    a downstream re-normalisation produces the same output regardless
    of whether the manifest is available.
    """
    try:
        event = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.exception("Calendar event JSON parse failed")
        return "<!-- normalization failed: could not parse event JSON -->\n"

    summary = event.get("summary") or (metadata or {}).get("summary") or "(no title)"
    status = event.get("status") or ""
    heading = (
        f"# (cancelled) {summary}" if status == "cancelled" else f"# {summary}"
    )

    parts: list[str] = [heading, ""]

    # ── Inline structural-metadata block ──
    when = _format_time_range(event.get("start"), event.get("end"))
    if when:
        parts.append(f"**When:** {when}")

    location = event.get("location") or ""
    if location:
        parts.append(f"**Where:** {location}")

    conf_link = _format_conference_link(event)
    if conf_link:
        parts.append(f"**Conference:** {conf_link}")

    organizer_str = _format_organizer(event.get("organizer"))
    if organizer_str:
        parts.append(f"**Organizer:** {organizer_str}")

    attendee_lines = _format_attendees(event.get("attendees"))
    if attendee_lines:
        parts.append("**Attendees:**")
        parts.extend(attendee_lines)

    # ── Description ──
    description_md = _render_description(event.get("description") or "")
    if description_md:
        parts.append("")
        parts.append("## Description")
        parts.append("")
        parts.append(description_md)

    # ── Attachments ──
    attachment_lines = _render_attachments(event.get("attachments"))
    if attachment_lines:
        parts.append("")
        parts.append("## Attachments")
        parts.append("")
        parts.extend(attachment_lines)

    output = "\n".join(parts)
    output = _EXCESSIVE_BLANKS.sub("\n\n", output)
    return f"{output.strip()}\n"
