"""Unit tests for :class:`src.harvester.calendar.client.GoogleCalendarClient`.

Mirrors ``test_gmail_client.py``. The Google service object is mocked
via ``unittest.mock`` — we test client semantics, not HTTP.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.harvester.calendar.client import (
    CalendarAPIError,
    CalendarAuthError,
    GoogleCalendarClient,
    _classify_http_error,
    _to_rfc3339,
)


# ── HTTP error classification ───────────────────────────────────


class _FakeResp(dict):
    def __init__(self, status: int, headers: dict | None = None) -> None:
        super().__init__(headers or {})
        self.status = status


class _FakeHttpError(Exception):
    def __init__(self, status: int, headers: dict | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.resp = _FakeResp(status, headers)


def test_classify_401_yields_auth_error():
    err = _classify_http_error(_FakeHttpError(401))
    assert isinstance(err, CalendarAuthError)
    assert err.status_code == 401


def test_classify_403_yields_auth_error():
    err = _classify_http_error(_FakeHttpError(403))
    assert isinstance(err, CalendarAuthError)


def test_classify_429_yields_retryable_with_retry_after():
    from src.harvester.calendar.client import _RetryableCalendarError

    err = _classify_http_error(_FakeHttpError(429, {"retry-after": "12"}))
    assert isinstance(err, _RetryableCalendarError)
    assert err.retry_after == 12.0


def test_classify_500_yields_retryable_without_retry_after():
    from src.harvester.calendar.client import _RetryableCalendarError

    err = _classify_http_error(_FakeHttpError(500))
    assert isinstance(err, _RetryableCalendarError)
    assert err.retry_after is None


def test_classify_404_yields_generic_api_error():
    err = _classify_http_error(_FakeHttpError(404))
    assert isinstance(err, CalendarAPIError)
    assert not isinstance(err, CalendarAuthError)


# ── _to_rfc3339 ─────────────────────────────────────────────────


def test_naive_datetime_assumed_utc():
    dt = datetime(2026, 4, 30, 14, 0, 0)
    assert _to_rfc3339(dt) == "2026-04-30T14:00:00Z"


def test_aware_datetime_converted_to_utc():
    from datetime import timedelta, timezone

    tz = timezone(timedelta(hours=-7))
    dt = datetime(2026, 4, 30, 7, 0, 0, tzinfo=tz)
    assert _to_rfc3339(dt) == "2026-04-30T14:00:00Z"


# ── Lazy service construction ───────────────────────────────────


def test_client_does_not_build_service_at_construction():
    client = GoogleCalendarClient("/nonexistent/creds.json", "/nonexistent/token.json")
    assert client._service is None


async def test_get_calendar_list_lazily_builds_service_and_calls_api():
    client = GoogleCalendarClient("/c.json", "/t.json")

    fake_service = MagicMock()
    fake_service.calendarList().list().execute.return_value = {
        "items": [{"id": "primary", "summary": "Personal", "primary": True}]
    }

    with patch.object(client, "_get_service", return_value=fake_service):
        result = await client.get_calendar_list()

    assert result["items"][0]["primary"] is True


async def test_get_calendar_list_translates_http_error_to_auth_error():
    client = GoogleCalendarClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.calendarList().list().execute.side_effect = _FakeHttpError(401)

    with patch.object(client, "_get_service", return_value=fake_service):
        with pytest.raises(CalendarAuthError):
            await client.get_calendar_list()


async def test_list_events_passes_window_and_pagination_params():
    client = GoogleCalendarClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.events().list().execute.return_value = {
        "items": [{"id": "e1"}],
        "nextPageToken": "abc",
    }

    with patch.object(client, "_get_service", return_value=fake_service):
        out = await client.list_events(
            "primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
            max_results=50,
        )

    assert out["items"][0]["id"] == "e1"
    list_call = fake_service.events().list
    list_call.assert_called_with(
        calendarId="primary",
        timeMin="2026-01-01T00:00:00Z",
        timeMax="2026-12-31T00:00:00Z",
        singleEvents=True,
        orderBy="startTime",
        showDeleted=False,
        maxResults=50,
    )


async def test_list_events_includes_updated_min_when_provided():
    client = GoogleCalendarClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.events().list().execute.return_value = {"items": []}

    with patch.object(client, "_get_service", return_value=fake_service):
        await client.list_events(
            "primary",
            time_min=datetime(2026, 1, 1),
            time_max=datetime(2026, 12, 31),
            updated_min=datetime(2026, 4, 22),
        )

    list_call = fake_service.events().list
    args = list_call.call_args
    assert args.kwargs["updatedMin"] == "2026-04-22T00:00:00Z"


async def test_get_event_calls_get_with_calendar_and_event_id():
    client = GoogleCalendarClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.events().get().execute.return_value = {"id": "e1"}

    with patch.object(client, "_get_service", return_value=fake_service):
        result = await client.get_event("primary", "e1")

    assert result["id"] == "e1"
    fake_service.events().get.assert_called_with(calendarId="primary", eventId="e1")
