"""End-to-end tests for :func:`src.harvester.calendar.normalizer.calendar_to_markdown`.

The Calendar normaliser produces **pure-body markdown** — no YAML
frontmatter, no metadata headers — to match the contract documented
on :class:`src.harvester.NormalizedDocument`. The first asserted
property is exactly that: the output never starts with ``---``.
"""

from __future__ import annotations

import json

from src.harvester.calendar.normalizer import calendar_to_markdown


def _event_bytes(**fields) -> bytes:
    base = {
        "id": "evt-1",
        "summary": "Project kickoff",
        "status": "confirmed",
        "start": {"dateTime": "2026-04-30T14:00:00Z"},
        "end": {"dateTime": "2026-04-30T15:00:00Z"},
    }
    base.update(fields)
    return json.dumps(base).encode("utf-8")


# ── Pure-body contract ───────────────────────────────────────────


def test_output_does_not_start_with_yaml_delimiter():
    out = calendar_to_markdown(_event_bytes(), {})
    assert not out.startswith("---")


def test_output_starts_with_summary_heading():
    out = calendar_to_markdown(_event_bytes(summary="Acme renewal"), {})
    first_line = out.lstrip("\n").splitlines()[0]
    assert first_line == "# Acme renewal"


def test_missing_summary_falls_back_to_no_title_marker():
    out = calendar_to_markdown(_event_bytes(summary=""), {})
    first_line = out.lstrip("\n").splitlines()[0]
    assert first_line == "# (no title)"


def test_metadata_summary_used_when_event_summary_empty():
    out = calendar_to_markdown(_event_bytes(summary=""), {"summary": "From manifest"})
    assert "# From manifest" in out


# ── Cancelled events ─────────────────────────────────────────────


def test_cancelled_event_prefixes_heading():
    out = calendar_to_markdown(
        _event_bytes(summary="Standup", status="cancelled"), {}
    )
    assert "# (cancelled) Standup" in out


# ── When-line rendering ──────────────────────────────────────────


def test_timed_event_when_line_renders_utc_range():
    out = calendar_to_markdown(_event_bytes(), {})
    assert "**When:** 2026-04-30 14:00 – 15:00 UTC" in out


def test_timed_event_with_offset_normalised_to_utc():
    """A -07:00 event should render in UTC (8 hours earlier in the local TZ)."""
    raw = _event_bytes(
        start={"dateTime": "2026-04-30T07:00:00-07:00"},
        end={"dateTime": "2026-04-30T08:00:00-07:00"},
    )
    out = calendar_to_markdown(raw, {})
    assert "**When:** 2026-04-30 14:00 – 15:00 UTC" in out


def test_all_day_single_day_renders_with_marker():
    raw = _event_bytes(
        start={"date": "2026-04-30"},
        end={"date": "2026-04-30"},
    )
    out = calendar_to_markdown(raw, {})
    assert "**When:** 2026-04-30 (all day)" in out


def test_all_day_multi_day_renders_range():
    raw = _event_bytes(
        start={"date": "2026-04-30"},
        end={"date": "2026-05-02"},
    )
    out = calendar_to_markdown(raw, {})
    assert "**When:** 2026-04-30 – 2026-05-02 (all day)" in out


def test_timed_event_across_days_renders_full_dates():
    raw = _event_bytes(
        start={"dateTime": "2026-04-30T23:30:00Z"},
        end={"dateTime": "2026-05-01T00:30:00Z"},
    )
    out = calendar_to_markdown(raw, {})
    assert "**When:** 2026-04-30 23:30 UTC – 2026-05-01 00:30 UTC" in out


# ── Where / Conference / Organizer / Attendees ───────────────────


def test_where_line_renders_when_location_present():
    raw = _event_bytes(location="Conference Room B")
    out = calendar_to_markdown(raw, {})
    assert "**Where:** Conference Room B" in out


def test_where_line_skipped_when_no_location():
    out = calendar_to_markdown(_event_bytes(), {})
    assert "**Where:**" not in out


def test_conference_link_rendered_as_markdown_link():
    raw = _event_bytes(
        conferenceData={
            "conferenceSolution": {"name": "Google Meet"},
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg"}
            ],
        }
    )
    out = calendar_to_markdown(raw, {})
    assert "**Conference:** [Google Meet](https://meet.google.com/abc-defg)" in out


def test_organizer_renders_name_and_email():
    raw = _event_bytes(
        organizer={"displayName": "Amy Chen", "email": "amy@acme.com"}
    )
    out = calendar_to_markdown(raw, {})
    assert "**Organizer:** Amy Chen <amy@acme.com>" in out


def test_attendees_render_with_response_status():
    raw = _event_bytes(
        attendees=[
            {"displayName": "Alice", "email": "alice@x.com", "responseStatus": "accepted"},
            {"displayName": "Bob", "email": "bob@y.com", "responseStatus": "tentative"},
        ]
    )
    out = calendar_to_markdown(raw, {})
    assert "**Attendees:**" in out
    assert "- Alice <alice@x.com> — accepted" in out
    assert "- Bob <bob@y.com> — tentative" in out


def test_attendees_section_skipped_when_empty():
    out = calendar_to_markdown(_event_bytes(), {})
    assert "**Attendees:**" not in out


# ── Description ──────────────────────────────────────────────────


def test_plaintext_description_passes_through():
    raw = _event_bytes(description="Discuss Q4 plan and align stakeholders.")
    out = calendar_to_markdown(raw, {})
    assert "## Description" in out
    assert "Discuss Q4 plan and align stakeholders." in out


def test_html_description_converted_to_markdown():
    raw = _event_bytes(description="<p>Agenda:</p><ul><li>Review</li><li>Plan</li></ul>")
    out = calendar_to_markdown(raw, {})
    assert "## Description" in out
    assert "Agenda:" in out
    # markdownify renders bullets as either "*" or "-"
    assert ("- Review" in out) or ("* Review" in out)


def test_description_section_skipped_when_empty():
    out = calendar_to_markdown(_event_bytes(), {})
    assert "## Description" not in out


# ── Attachments ──────────────────────────────────────────────────


def test_attachments_section_renders_drive_links():
    raw = _event_bytes(
        attachments=[
            {"title": "Q4 doc", "fileUrl": "https://docs.google.com/document/abc"},
            {"title": "Budget sheet", "fileUrl": "https://docs.google.com/sheet/xyz"},
        ]
    )
    out = calendar_to_markdown(raw, {})
    assert "## Attachments" in out
    assert "- [Q4 doc](https://docs.google.com/document/abc)" in out
    assert "- [Budget sheet](https://docs.google.com/sheet/xyz)" in out


def test_attachments_section_skipped_when_empty():
    out = calendar_to_markdown(_event_bytes(), {})
    assert "## Attachments" not in out


# ── Cleanup / defensive ──────────────────────────────────────────


def test_excessive_blank_lines_collapsed():
    raw = _event_bytes(description="line one\n\n\n\nline two")
    out = calendar_to_markdown(raw, {})
    assert "\n\n\n" not in out


def test_output_ends_with_single_trailing_newline():
    out = calendar_to_markdown(_event_bytes(), {})
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_malformed_json_returns_failure_marker():
    out = calendar_to_markdown(b"{not json", {})
    assert "<!-- normalization failed" in out
