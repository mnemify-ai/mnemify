"""Tests for src.terrain.utils.deadlines — deterministic deadline resolution."""

from __future__ import annotations

from datetime import date

import pytest

from src.terrain.utils.deadlines import parse_anchor, resolve_deadline

# Wednesday, 2026-04-15 — matches the obsidian fixture vault's daily note.
ANCHOR = date(2026, 4, 15)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Absolute ISO dates.
        ("due 2026-05-01", "2026-05-01"),
        ("ship by 2026-05", "2026-05-31"),
        # Month + day (year inferred forward from anchor).
        ("finalize by April 30", "2026-04-30"),
        ("by Apr 30th", "2026-04-30"),
        ("due 30 April", "2026-04-30"),
        ("deadline March 1", "2027-03-01"),  # already past → next year
        ("send it by January 5, 2027", "2027-01-05"),
        # Month only → end of that month.
        ("by end of April", "2026-04-30"),
        ("wrap up by February", "2027-02-28"),
        # Quarters.
        ("commit by Q3", "2026-09-30"),
        ("target Q1 2027", "2027-03-31"),
        ("by q2", "2026-06-30"),
        # Relative counts.
        ("remind me in 1 week", "2026-04-22"),
        ("in two weeks", "2026-04-29"),
        ("within 3 days", "2026-04-18"),
        ("in a month", "2026-05-15"),
        # Day words.
        ("tomorrow", "2026-04-16"),
        ("get it done today", "2026-04-15"),
        # End-of-period.
        ("by end of week", "2026-04-19"),
        ("end of the month", "2026-04-30"),
        ("by EOD", "2026-04-15"),
        ("eow", "2026-04-19"),
        ("by end of quarter", "2026-06-30"),
        ("end of year", "2026-12-31"),
        # Next-period.
        ("next week", "2026-04-26"),
        ("next month", "2026-05-31"),
        # Weekdays (anchor is a Wednesday).
        ("by Friday", "2026-04-17"),
        ("due Monday", "2026-04-20"),
        ("by Wednesday", "2026-04-22"),  # bare weekday on that weekday → next one
        ("next Friday", "2026-04-24"),
        # Not deadlines.
        ("no deadline here", None),
        ("", None),
        (None, None),
        # ID-like tokens must not half-match as dates (regression: "bad month
        # number 89" crashed whole compiles before the digit lookarounds).
        ("ticket 2024-8934 blocked", None),
        ("see JIRA-2026-1234", None),
        ("ref 12026-05-01 is not a date", None),
    ],
)
def test_resolve_deadline(text, expected):
    assert resolve_deadline(text, ANCHOR) == expected


def test_explicit_date_beats_weekday_mention():
    assert resolve_deadline("by Friday, April 30", ANCHOR) == "2026-04-30"


def test_absolute_dates_resolve_without_anchor():
    assert resolve_deadline("due 2026-05-01", None) == "2026-05-01"
    assert resolve_deadline("Q3 2026", None) == "2026-09-30"


def test_relative_phrases_need_an_anchor():
    assert resolve_deadline("in 1 week", None) is None
    assert resolve_deadline("by Friday", None) is None
    assert resolve_deadline("by April 30", None) is None  # year unknowable


def test_parse_anchor_tolerates_common_shapes():
    assert parse_anchor("2026-04-15") == date(2026, 4, 15)
    assert parse_anchor("2026-04-15T08:30:00Z") == date(2026, 4, 15)
    assert parse_anchor("2026-04-15T08:30:00+02:00") == date(2026, 4, 15)
    assert parse_anchor(None) is None
    assert parse_anchor("garbage") is None
    assert parse_anchor("2024-8934") is None  # ID-like token, not a date


def test_invalid_calendar_dates_are_rejected():
    assert resolve_deadline("due 2026-13-01", ANCHOR) is None
