"""Unit tests for :class:`src.harvester.calendar.events.EventExtractor`.

Mirrors ``test_gmail_threads.py``: pagination, the safety cap, and
defensive empty-page handling. The client is mocked so these tests
focus on extractor semantics, not HTTP.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

from src.harvester.calendar.client import GoogleCalendarClient
from src.harvester.calendar.events import EventExtractor


def _page(items: list[dict], *, next_page_token: str | None = None) -> dict:
    page: dict = {"items": items}
    if next_page_token is not None:
        page["nextPageToken"] = next_page_token
    return page


def _evt(event_id: str, summary: str = "Standup") -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "status": "confirmed",
        "start": {"dateTime": "2026-04-30T14:00:00Z"},
        "end": {"dateTime": "2026-04-30T15:00:00Z"},
    }


async def _collect(iterator) -> list[dict]:
    out: list[dict] = []
    async for item in iterator:
        out.append(item)
    return out


# ── Pagination ──────────────────────────────────────────────────


async def test_yields_events_from_single_page():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.list_events.return_value = _page([_evt("e1"), _evt("e2")])
    ext = EventExtractor(client)

    out = await _collect(
        ext.list_events(
            calendar_id="primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
        )
    )

    assert [e["id"] for e in out] == ["e1", "e2"]
    client.list_events.assert_awaited_once()


async def test_pagination_terminates_on_absent_next_page_token():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.list_events.side_effect = [
        _page([_evt("e1")], next_page_token="page2"),
        _page([_evt("e2")]),  # no nextPageToken → stop
    ]
    ext = EventExtractor(client)

    out = await _collect(
        ext.list_events(
            calendar_id="primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
        )
    )

    assert [e["id"] for e in out] == ["e1", "e2"]
    assert client.list_events.await_count == 2


async def test_pagination_terminates_on_empty_items_defensive():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.list_events.side_effect = [
        _page([_evt("e1")], next_page_token="page2"),
        _page([], next_page_token="still-not-none"),
    ]
    ext = EventExtractor(client)

    out = await _collect(
        ext.list_events(
            calendar_id="primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
        )
    )

    assert [e["id"] for e in out] == ["e1"]


# ── max_events cap ──────────────────────────────────────────────


async def test_max_events_cap_stops_mid_page():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.list_events.return_value = _page(
        [_evt("e1"), _evt("e2"), _evt("e3")],
        next_page_token="more",
    )
    ext = EventExtractor(client)

    out = await _collect(
        ext.list_events(
            calendar_id="primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
            max_events=2,
        )
    )

    assert [e["id"] for e in out] == ["e1", "e2"]


# ── updated_min plumbing ────────────────────────────────────────


async def test_updated_min_passed_to_client():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.list_events.return_value = _page([])
    ext = EventExtractor(client)

    anchor = datetime(2026, 4, 22, 0, 0)
    await _collect(
        ext.list_events(
            calendar_id="primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
            updated_min=anchor,
        )
    )

    call = client.list_events.await_args
    assert call.kwargs.get("updated_min") == anchor


# ── get_full_event ──────────────────────────────────────────────


async def test_get_full_event_passes_through_to_client():
    client = AsyncMock(spec=GoogleCalendarClient)
    client.get_event.return_value = {"id": "e1", "summary": "x"}
    ext = EventExtractor(client)

    result = await ext.get_full_event("primary", "e1")

    assert result["id"] == "e1"
    client.get_event.assert_awaited_once_with("primary", "e1")
