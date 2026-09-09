"""Unit tests for :func:`src.harvester.gmail.query.build_query`.

Gmail's search syntax is small but easy to get subtly wrong:
``CATEGORY_PROMOTIONS`` is addressed via ``-category:promotions`` (not
``-label:CATEGORY_PROMOTIONS``); ``after:`` takes integer epoch seconds
in UTC; multi-sender ``from:`` clauses must be wrapped in parentheses
with ``OR`` joins. These tests pin the format exactly so a regression
gets caught at unit-test time, not in a live harvest.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.harvester.gmail.query import build_query


# ── Empty / defaults ────────────────────────────────────────────


def test_empty_inputs_yield_empty_query():
    """All defaults → empty string. Gmail treats this as 'every thread'."""
    assert build_query() == ""


def test_label_filter_empty_omits_clause():
    """An empty label_filter list does not add ``label:`` to the query."""
    assert build_query(label_filter=[]) == ""


# ── since → after:<epoch> ───────────────────────────────────────


def test_since_naive_treated_as_utc():
    """Naive datetimes are assumed UTC for the epoch conversion."""
    since = datetime(2026, 4, 22, 0, 0)  # 2026-04-22 UTC midnight
    expected_epoch = int(datetime(2026, 4, 22, tzinfo=timezone.utc).timestamp())
    assert build_query(since=since) == f"after:{expected_epoch}"


def test_since_tz_aware_converted_to_utc():
    """Timezone-aware datetimes are normalised to UTC before conversion."""
    # 2026-04-22 12:00 in +05:30 == 2026-04-22 06:30 UTC
    from datetime import timedelta
    tz_ist = timezone(timedelta(hours=5, minutes=30))
    since = datetime(2026, 4, 22, 12, 0, tzinfo=tz_ist)
    expected_epoch = int(datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc).timestamp())
    assert build_query(since=since) == f"after:{expected_epoch}"


# ── Label filter / exclude ──────────────────────────────────────


def test_user_label_filter_renders_label_prefix():
    assert build_query(label_filter=["Inbox"]) == "label:Inbox"


def test_user_label_exclude_renders_minus_label_prefix():
    assert build_query(label_exclude=["Spam"]) == "-label:Spam"


def test_system_category_uses_category_prefix_not_label():
    """``CATEGORY_PROMOTIONS`` must become ``category:promotions``."""
    out = build_query(label_exclude=["CATEGORY_PROMOTIONS"])
    assert out == "-category:promotions"


def test_default_promotions_social_exclude_default_renders():
    out = build_query(
        label_exclude=["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"]
    )
    assert out == "-category:promotions -category:social"


def test_multiple_user_labels_join_with_space():
    """Multiple include-labels render as space-joined ``label:`` clauses (Gmail AND)."""
    out = build_query(label_filter=["Inbox", "Important"])
    assert out == "label:Inbox label:Important"


# ── Sender allowlist ────────────────────────────────────────────


def test_single_sender_renders_without_parens():
    out = build_query(sender_allowlist=["amy@acme.com"])
    assert out == "from:amy@acme.com"


def test_multi_sender_wraps_in_parens_with_or():
    out = build_query(sender_allowlist=["amy@acme.com", "sarah@tensor.io"])
    assert out == "from:(amy@acme.com OR sarah@tensor.io)"


# ── Composition ─────────────────────────────────────────────────


def test_full_composition_orders_since_exclude_filter_sender():
    """Full query composes in stable order: after, exclude, filter, sender."""
    since = datetime(2026, 4, 22, 0, 0)
    epoch = int(datetime(2026, 4, 22, tzinfo=timezone.utc).timestamp())
    out = build_query(
        since=since,
        label_filter=["Inbox"],
        label_exclude=["CATEGORY_PROMOTIONS"],
        sender_allowlist=["amy@acme.com"],
    )
    assert out == (
        f"after:{epoch} -category:promotions label:Inbox from:amy@acme.com"
    )
