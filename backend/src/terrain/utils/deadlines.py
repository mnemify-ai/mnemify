"""Deterministic deadline resolution for attention signals.

Turns a natural-language deadline phrase ("by Friday", "in 1 week", "end of
April", "by Q3") into an ISO ``YYYY-MM-DD`` date, resolved against an *anchor*
date — the document's effective authored date, never wall-clock today. LLM
signal drafts are cached by content hash across compiles, so anything
time-relative must be resolved here, deterministically, on every compile.

Hand-rolled on purpose: the phrase inventory is small and closed, and a
``dateparser`` dependency would drag in locale machinery we don't need.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

__all__ = ["parse_anchor", "resolve_deadline"]


# YYYY-MM(-DD) anywhere in the text (same shape as compiler._ISO_DATE_RE).
# Digit lookarounds keep ID-like tokens ("2024-8934") from half-matching.
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "April 30", "Apr 30th, 2026", "30 April", "30th of April 2026"
_MONTH_DAY_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b",
    re.IGNORECASE,
)
_DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_ALT})\.?(?:\s*,?\s*(\d{{4}}))?\b",
    re.IGNORECASE,
)
# Bare "by April" / "mid April" — resolve to end of that month (a month with no
# day reads as "sometime during", so the last day is the deadline).
_MONTH_ONLY_RE = re.compile(
    rf"\b(?:by|until|before|end of|mid|in)\s+({_MONTH_ALT})\b(?!\s+\d)",
    re.IGNORECASE,
)

_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_WEEKDAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})
_WEEKDAY_ALT = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_WEEKDAY_RE = re.compile(rf"\b(next\s+)?({_WEEKDAY_ALT})\b", re.IGNORECASE)

_RELATIVE_RE = re.compile(
    r"\b(?:in|within)\s+(a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(day|week|month)s?\b",
    re.IGNORECASE,
)
_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_QUARTER_RE = re.compile(r"\bq([1-4])(?:\s*(?:of\s*)?(\d{4}))?\b", re.IGNORECASE)
_END_OF_RE = re.compile(
    r"\b(?:by\s+)?(?:end\s+of\s+(?:the\s+)?(day|week|month|quarter|year)|(eod|eow|eom|eoq|eoy))\b",
    re.IGNORECASE,
)
_TOMORROW_RE = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TODAY_RE = re.compile(r"\b(today|by\s+tonight|tonight)\b", re.IGNORECASE)
_NEXT_UNIT_RE = re.compile(r"\bnext\s+(week|month|quarter|year)\b", re.IGNORECASE)


def parse_anchor(value: str | None) -> date | None:
    """Tolerant ISO parse of a document timestamp into a date (``Z`` ok)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        pass
    match = _ISO_RE.search(value)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1))
    return None


def resolve_deadline(text: str | None, anchor: date | None) -> str | None:
    """First deadline found in ``text``, as ISO YYYY-MM-DD, else None.

    Absolute dates resolve without an anchor; relative phrases ("Friday",
    "in 1 week", "end of month") require one and return None otherwise.
    Branch order goes most-explicit → most-ambiguous so "by Friday, April 30"
    trusts the full date over the weekday.
    """
    if not text:
        return None

    match = _ISO_RE.search(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            day = int(match.group(3)) if match.group(3) else _last_day(year, month)
            resolved = _safe_date(year, month, day)
            if resolved:
                return resolved.isoformat()

    for pattern, month_group, day_group in ((_MONTH_DAY_RE, 1, 2), (_DAY_MONTH_RE, 2, 1)):
        match = pattern.search(text)
        if match:
            month = _MONTHS[match.group(month_group).lower().rstrip(".")]
            day = int(match.group(day_group))
            if match.group(3):
                year = int(match.group(3))
            elif anchor is not None:
                year = _infer_year(anchor, month, day)
            else:
                continue  # month+day with no year is relative to the anchor
            resolved = _safe_date(year, month, day)
            if resolved:
                return resolved.isoformat()

    match = _QUARTER_RE.search(text)
    if match:
        quarter = int(match.group(1))
        month = quarter * 3
        if match.group(2):
            year = int(match.group(2))
        elif anchor:
            # A bare "Q3" means the next Q3-end on or after the anchor.
            year = anchor.year + (1 if anchor > date(anchor.year, month, _last_day(anchor.year, month)) else 0)
        else:
            return None
        return date(year, month, _last_day(year, month)).isoformat()

    match = _MONTH_ONLY_RE.search(text)
    if match:
        month = _MONTHS[match.group(1).lower().rstrip(".")]
        if anchor is None:
            return None
        year = anchor.year + (1 if month < anchor.month else 0)
        return date(year, month, _last_day(year, month)).isoformat()

    if anchor is None:
        return None

    if _TOMORROW_RE.search(text):
        return (anchor + timedelta(days=1)).isoformat()
    if _TODAY_RE.search(text):
        return anchor.isoformat()

    match = _RELATIVE_RE.search(text)
    if match:
        count = _NUM_WORDS.get(match.group(1).lower()) or int(match.group(1))
        unit = match.group(2).lower()
        if unit == "day":
            return (anchor + timedelta(days=count)).isoformat()
        if unit == "week":
            return (anchor + timedelta(weeks=count)).isoformat()
        return _add_months(anchor, count).isoformat()

    match = _END_OF_RE.search(text)
    if match:
        unit = (match.group(1) or "").lower() or {
            "eod": "day", "eow": "week", "eom": "month", "eoq": "quarter", "eoy": "year",
        }[match.group(2).lower()]
        return _end_of(anchor, unit).isoformat()

    match = _NEXT_UNIT_RE.search(text)
    if match:
        unit = match.group(1).lower()
        if unit == "week":
            return _end_of(anchor + timedelta(weeks=1), "week").isoformat()
        if unit == "month":
            return _end_of(_add_months(anchor, 1), "month").isoformat()
        if unit == "quarter":
            return _end_of(_add_months(_end_of(anchor, "quarter"), 1), "quarter").isoformat()
        return date(anchor.year + 1, 12, 31).isoformat()

    match = _WEEKDAY_RE.search(text)
    if match:
        target = _WEEKDAYS[match.group(2).lower()]
        ahead = (target - anchor.weekday()) % 7
        if ahead == 0 and not match.group(1):
            ahead = 7  # bare "Friday" on a Friday means the coming one
        if match.group(1):
            ahead = ahead + 7 if ahead < 7 else ahead
        return (anchor + timedelta(days=ahead)).isoformat()

    return None


def _infer_year(anchor: date, month: int, day: int) -> int:
    """Year for a month+day with none stated: the next occurrence on or after
    the anchor, since deadlines point forward."""
    candidate = _safe_date(anchor.year, month, day)
    if candidate and candidate >= anchor:
        return anchor.year
    return anchor.year + 1


def _safe_date(year: int, month: int, day: int) -> date | None:
    if not (1 <= month <= 12):
        return None
    try:
        return date(year, month, min(day, _last_day(year, month)))
    except ValueError:
        return None


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _add_months(anchor: date, count: int) -> date:
    month_index = anchor.month - 1 + count
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(anchor.day, _last_day(year, month)))


def _end_of(anchor: date, unit: str) -> date:
    if unit == "day":
        return anchor
    if unit == "week":
        return anchor + timedelta(days=6 - anchor.weekday())
    if unit == "month":
        return date(anchor.year, anchor.month, _last_day(anchor.year, anchor.month))
    if unit == "quarter":
        month = ((anchor.month - 1) // 3 + 1) * 3
        return date(anchor.year, month, _last_day(anchor.year, month))
    return date(anchor.year, 12, 31)
