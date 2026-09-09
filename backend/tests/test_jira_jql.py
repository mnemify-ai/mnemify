"""Unit tests for :func:`src.harvester.jira.jql.build_jql` (ATL-23).

The JQL format is brittle: Atlassian's parser rejects strings with
seconds, timezone designators, or unquoted datetime values with an
HTTP 400 error and no useful diagnostic. These tests pin the format
string exactly so a regression is caught at unit-test time rather than
in a live harvest.

Coverage:
- Single project, no ``since``.
- Single project with ``since`` — exact format string.
- Multi-project, no ``since``.
- Multi-project with ``since``.
- Seconds / microseconds get stripped.
- Empty project list → ``ValueError``.
- Timezone-aware datetime gets normalised to naive UTC.
- Invalid project keys (hyphens, lowercase) → ``ValueError``.
- Order of keys is preserved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.harvester.jira.jql import build_jql


# ── 1. Single project ────────────────────────────────────────────


def test_single_project_no_since():
    """Single project with no ``since`` omits the ``updated`` clause."""
    assert build_jql(["ABC"]) == "project = ABC ORDER BY updated DESC"


def test_single_project_with_since():
    """Single project with ``since`` renders the exact Atlassian format."""
    since = datetime(2026, 4, 19, 13, 45)
    assert build_jql(["ABC"], since=since) == (
        'project = ABC AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


# ── 2. Multi-project ─────────────────────────────────────────────


def test_multi_project_no_since():
    """Multi-project renders ``project in (...)`` and no ``updated`` clause."""
    assert build_jql(["ABC", "DEF"]) == "project in (ABC, DEF) ORDER BY updated DESC"


def test_multi_project_with_since():
    """Multi-project with ``since`` renders the combined clause."""
    since = datetime(2026, 4, 19, 13, 45)
    assert build_jql(["ABC", "DEF"], since=since) == (
        'project in (ABC, DEF) AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


def test_multi_project_preserves_order():
    """Caller-supplied order is preserved — important for debug log readability."""
    assert build_jql(["ZULU", "ALPHA", "BRAVO"]) == (
        "project in (ZULU, ALPHA, BRAVO) ORDER BY updated DESC"
    )


# ── 3. Datetime normalisation ────────────────────────────────────


def test_since_strips_seconds_and_microseconds():
    """Seconds / microseconds in the input are dropped before formatting."""
    since = datetime(2026, 4, 19, 13, 45, 59, 123456)
    assert build_jql(["ABC"], since=since) == (
        'project = ABC AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


def test_since_tz_aware_converted_to_naive_utc():
    """Aware datetimes are normalised to UTC and rendered without a tz suffix.

    JQL has no timezone syntax — the value is interpreted in the Jira
    instance's configured timezone. Converting to UTC first gives the
    caller a predictable, timezone-independent anchor (at the cost of a
    potential wall-clock offset versus the instance tz, which is
    acceptable for incremental ``since`` filters because the manifest's
    content-hash dedup layer absorbs spurious over-fetches).
    """
    # 2026-04-19 09:45 in UTC-4 == 13:45 UTC.
    tz_minus_4 = timezone(timedelta(hours=-4))
    since = datetime(2026, 4, 19, 9, 45, tzinfo=tz_minus_4)
    assert build_jql(["ABC"], since=since) == (
        'project = ABC AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


def test_since_already_utc_aware():
    """UTC-aware input renders identically to the equivalent naive UTC."""
    since = datetime(2026, 4, 19, 13, 45, tzinfo=timezone.utc)
    assert build_jql(["ABC"], since=since) == (
        'project = ABC AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


# ── 4. Validation ────────────────────────────────────────────────


def test_empty_project_keys_raises():
    """Empty project list must raise — never produce an un-scoped JQL."""
    with pytest.raises(ValueError, match="at least one project key"):
        build_jql([])


def test_hyphenated_project_key_raises():
    """Hyphenated keys would collide with Jira's issue-key syntax."""
    with pytest.raises(ValueError, match="Invalid Jira project key"):
        build_jql(["ABC-DEF"])


def test_lowercase_project_key_raises():
    """Jira Cloud project keys are uppercase; reject lowercase at the boundary."""
    with pytest.raises(ValueError, match="Invalid Jira project key"):
        build_jql(["abc"])


def test_single_letter_project_key_raises():
    """The regex requires at least two characters (`[A-Z][A-Z0-9]+`)."""
    with pytest.raises(ValueError, match="Invalid Jira project key"):
        build_jql(["A"])


def test_non_string_project_key_raises():
    """Defensive: a non-string key must not slip through and produce odd JQL."""
    with pytest.raises(ValueError):
        build_jql([123])  # type: ignore[list-item]
