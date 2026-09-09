"""Unit tests for :func:`src.harvester.calendar.fields.flatten_event_fields`.

The flatten function is the single place where Calendar's event JSON is
projected into the manifest's ``documents.metadata`` JSON column. Every
quirky shape (dateTime vs date, conferenceData entry-points, recurring
masters vs instances, missing organizer/attendees) gets pinned here.
"""

from __future__ import annotations

from src.harvester.calendar.fields import flatten_event_fields


# ── Inline event builders ────────────────────────────────────────


def _timed(start: str, end: str, **extra) -> dict:
    base = {
        "id": "evt-1",
        "summary": "Standup",
        "status": "confirmed",
        "start": {"dateTime": start, "timeZone": "America/Los_Angeles"},
        "end": {"dateTime": end, "timeZone": "America/Los_Angeles"},
        "htmlLink": "https://www.google.com/calendar/event?eid=evt-1",
        "created": "2026-04-01T10:00:00.000Z",
        "updated": "2026-04-15T09:21:33.123Z",
    }
    base.update(extra)
    return base


def _all_day(date: str, end_date: str | None = None, **extra) -> dict:
    base = {
        "id": "evt-allday",
        "summary": "Vacation",
        "status": "confirmed",
        "start": {"date": date},
        "end": {"date": end_date or date},
        "htmlLink": "https://www.google.com/calendar/event?eid=evt-allday",
    }
    base.update(extra)
    return base


# ── Time formatting ──────────────────────────────────────────────


def test_timed_event_emits_rfc3339_utc_strings():
    """A timed event with a -07:00 offset should normalize to ``Z`` UTC."""
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00-07:00", "2026-04-30T15:00:00-07:00"),
        calendar_id="primary",
    )
    assert out["start"] == "2026-04-30T21:00:00Z"
    assert out["end"] == "2026-04-30T22:00:00Z"
    assert out["all_day"] is False


def test_all_day_event_emits_date_only():
    out = flatten_event_fields(_all_day("2026-04-30"), calendar_id="primary")
    assert out["start"] == "2026-04-30"
    assert out["end"] == "2026-04-30"
    assert out["all_day"] is True


def test_multi_day_all_day_event():
    out = flatten_event_fields(
        _all_day("2026-04-30", end_date="2026-05-02"),
        calendar_id="primary",
    )
    assert out["start"] == "2026-04-30"
    assert out["end"] == "2026-05-02"
    assert out["all_day"] is True


def test_missing_start_does_not_crash():
    out = flatten_event_fields(
        {"id": "x", "summary": "no time", "status": "confirmed"},
        calendar_id="primary",
    )
    assert out["start"] == ""
    assert out["end"] == ""
    assert out["all_day"] is False


# ── Organizer / attendees ────────────────────────────────────────


def test_organizer_email_and_name_extracted():
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        organizer={"email": "amy@acme.com", "displayName": "Amy Chen"},
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["organizer_email"] == "amy@acme.com"
    assert out["organizer_name"] == "Amy Chen"


def test_attendee_emails_dedupe_in_order():
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        attendees=[
            {"email": "a@x.com"},
            {"email": "b@x.com"},
            {"email": "a@x.com"},  # dup
        ],
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["attendee_emails"] == ["a@x.com", "b@x.com"]
    assert out["attendee_count"] == 3  # raw count includes the dup


def test_no_attendees_yields_empty_list():
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z"),
        calendar_id="primary",
    )
    assert out["attendee_emails"] == []
    assert out["attendee_count"] == 0


# ── Conference URL ───────────────────────────────────────────────


def test_conference_url_extracted_from_video_entrypoint():
    """``conferenceData.entryPoints`` may have video + phone + sip; pick video."""
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        conferenceData={
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+1-555-0100"},
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"},
            ]
        },
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["conference_url"] == "https://meet.google.com/abc-defg-hij"


def test_conference_url_falls_back_to_legacy_hangout_link():
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        hangoutLink="https://hangouts.google.com/legacy",
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["conference_url"] == "https://hangouts.google.com/legacy"


def test_no_conference_url_yields_empty():
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z"),
        calendar_id="primary",
    )
    assert out["conference_url"] == ""


# ── Recurrence ───────────────────────────────────────────────────


def test_master_recurring_event_marked_is_recurring():
    """A master event has top-level ``recurrence`` (RRULE strings)."""
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TH"],
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["is_recurring"] is True
    assert out["recurring_event_id"] == ""


def test_instance_of_recurring_event_marked_is_recurring():
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        id="evt-inst",
        recurringEventId="evt-master",
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["is_recurring"] is True
    assert out["recurring_event_id"] == "evt-master"


def test_one_off_event_not_recurring():
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z"),
        calendar_id="primary",
    )
    assert out["is_recurring"] is False


# ── Status / cancellation ────────────────────────────────────────


def test_status_passes_through():
    cancelled = _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z", status="cancelled")
    out = flatten_event_fields(cancelled, calendar_id="primary")
    assert out["status"] == "cancelled"


# ── Identifiers and counts ───────────────────────────────────────


def test_calendar_id_threaded_through():
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z"),
        calendar_id="team-acme@group.calendar.google.com",
    )
    assert out["calendar_id"] == "team-acme@group.calendar.google.com"


def test_attachment_count():
    event = _timed(
        "2026-04-30T14:00:00Z",
        "2026-04-30T15:00:00Z",
        attachments=[
            {"title": "agenda.pdf", "fileUrl": "https://drive.google.com/1"},
            {"title": "notes.doc", "fileUrl": "https://drive.google.com/2"},
        ],
    )
    out = flatten_event_fields(event, calendar_id="primary")
    assert out["attachment_count"] == 2


def test_document_type_is_event():
    out = flatten_event_fields(
        _timed("2026-04-30T14:00:00Z", "2026-04-30T15:00:00Z"),
        calendar_id="primary",
    )
    assert out["document_type"] == "event"
