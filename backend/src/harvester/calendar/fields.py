"""Google Calendar event JSON → flat metadata dict.

Analogue of :func:`src.harvester.gmail.fields.flatten_thread_fields`.
The plugin keeps the full event JSON in :class:`RawDocument.content`
and uses this flat dict only for filter / manifest / compiler metadata,
so the projection is non-lossy in the same sense — body content
(description, attendee responses) is summarised here, not dropped.

Helpers handle the awkward parts of the Calendar shape:

- Times come in two flavours — ``dateTime`` for timed events, ``date``
  for all-day events. The flatten dict surfaces both as RFC3339-UTC
  strings plus an ``all_day`` boolean.
- ``conferenceData`` is a nested envelope; the conference URL lives in
  ``conferenceData.entryPoints[*].uri`` filtered to the ``video`` entry.
- Recurrence: master events have a top-level ``recurrence`` array of
  RRULE strings; instances of recurring events have ``recurringEventId``.
  Both flow through to ``is_recurring`` for easy filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _format_event_time(slot: dict | None) -> tuple[str, bool]:
    """Convert a Calendar ``start``/``end`` slot to ``(rfc3339_utc, all_day)``.

    Calendar emits one of two shapes:

    - Timed event:  ``{"dateTime": "2026-04-30T14:00:00-07:00", "timeZone": "..."}``
    - All-day:      ``{"date": "2026-04-30"}``

    Returns ``("", False)`` for missing or malformed slots so the
    metadata column never carries ``None`` for these fields.
    """
    if not slot:
        return ("", False)

    date_time = slot.get("dateTime")
    if date_time:
        try:
            # ``fromisoformat`` on 3.11+ handles offsets; for older
            # interpreters Calendar emits ``+00:00`` form which is
            # natively supported.
            dt = datetime.fromisoformat(date_time)
        except ValueError:
            return (date_time, False)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return (dt.strftime("%Y-%m-%dT%H:%M:%SZ"), False)

    date_only = slot.get("date")
    if date_only:
        # All-day events store a calendar date with no timezone. Surface
        # the raw date verbatim — converting to UTC midnight would imply
        # precision the source doesn't have.
        return (date_only, True)

    return ("", False)


def _extract_conference_url(event: dict) -> str:
    """Pull the video conference URL out of ``conferenceData.entryPoints``.

    Returns ``""`` for events with no conference attached. Some events
    have multiple entry points (video + phone + sip); we prefer the
    ``video`` entry, which is what users mean when they say "the meet
    link."
    """
    conf = event.get("conferenceData") or {}
    entries = conf.get("entryPoints") or []
    for entry in entries:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    # Some older event shapes have ``hangoutLink`` at the top level.
    return event.get("hangoutLink") or ""


def _attendee_emails(event: dict) -> list[str]:
    """Return the list of attendee email addresses, deduplicated, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for attendee in event.get("attendees") or ():
        email = attendee.get("email")
        if email and email not in seen:
            seen.add(email)
            out.append(email)
    return out


def flatten_event_fields(event: dict, *, calendar_id: str) -> dict:
    """Project a raw Calendar event JSON into the flat metadata dict.

    Output keys (the manifest's ``documents.metadata`` JSON column):

    - ``document_type``: always ``"event"``.
    - ``summary``: event title.
    - ``calendar_id``: the calendar this event was harvested from.
    - ``event_id``: Google's unique event identifier.
    - ``url``: ``htmlLink`` — the deep-link to the event in the web UI.
    - ``start`` / ``end``: RFC3339 UTC strings (``YYYY-MM-DDTHH:MM:SSZ``)
      for timed events, ``YYYY-MM-DD`` for all-day events.
    - ``all_day``: True when the event uses ``start.date`` (no time).
    - ``status``: ``confirmed`` | ``tentative`` | ``cancelled``.
    - ``organizer_email`` / ``organizer_name``: from ``organizer``.
    - ``attendee_emails``: deduped list of attendee addresses.
    - ``attendee_count``: convenience counter.
    - ``location``: free-form location string (often empty).
    - ``conference_url``: video-conference link (Meet/Zoom/Teams) or "".
    - ``is_recurring``: True if this event has an RRULE or is an
      instance of a recurring series.
    - ``recurring_event_id``: master event ID when this is an instance.
    - ``created`` / ``updated``: raw RFC3339 timestamps from Calendar.
    - ``attachment_count``: number of Drive attachments on the event.
    """
    organizer = event.get("organizer") or {}
    start_str, all_day_start = _format_event_time(event.get("start"))
    end_str, _all_day_end = _format_event_time(event.get("end"))

    is_master_recurring = bool(event.get("recurrence"))
    recurring_event_id = event.get("recurringEventId") or ""
    is_recurring = is_master_recurring or bool(recurring_event_id)

    return {
        "document_type": "event",
        "summary": event.get("summary") or "",
        "calendar_id": calendar_id,
        "event_id": event.get("id") or "",
        "url": event.get("htmlLink") or "",
        "start": start_str,
        "end": end_str,
        "all_day": all_day_start,
        "status": event.get("status") or "",
        "organizer_email": organizer.get("email") or "",
        "organizer_name": organizer.get("displayName") or "",
        "attendee_emails": _attendee_emails(event),
        "attendee_count": len(event.get("attendees") or ()),
        "location": event.get("location") or "",
        "conference_url": _extract_conference_url(event),
        "is_recurring": is_recurring,
        "recurring_event_id": recurring_event_id,
        "created": event.get("created") or "",
        "updated": event.get("updated") or "",
        "attachment_count": len(event.get("attachments") or ()),
    }
