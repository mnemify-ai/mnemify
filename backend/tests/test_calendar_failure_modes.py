"""Edge-case tests for the Calendar plugin.

Covers paths that are easy to write the happy-path code for but easy
to break under malformed responses, OAuth failures, or unusual events.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.harvester import DocRef
from src.harvester.calendar import CalendarConfig, GoogleCalendarHarvesterPlugin
from src.harvester.calendar.client import (
    CalendarAPIError,
    CalendarAuthError,
    GoogleCalendarClient,
)
from src.harvester.calendar.fields import flatten_event_fields
from src.harvester.calendar.normalizer import calendar_to_markdown


def _plugin() -> tuple[GoogleCalendarHarvesterPlugin, AsyncMock]:
    cfg = CalendarConfig()
    mock = AsyncMock(spec=GoogleCalendarClient)
    return GoogleCalendarHarvesterPlugin(cfg, client=mock), mock


# ── Auth errors during harvesting ────────────────────────────────


async def test_auth_error_during_list_propagates():
    plugin, mock = _plugin()
    mock.list_events.side_effect = CalendarAuthError("token revoked", status_code=401)

    with pytest.raises(CalendarAuthError):
        await plugin.list_documents()


async def test_api_error_during_fetch_propagates():
    plugin, mock = _plugin()
    mock.get_event.side_effect = CalendarAPIError("server error", status_code=500)
    doc = DocRef(
        source_id="e1",
        title="x",
        source_type="calendar",
        metadata={"calendar_id": "primary"},
    )

    with pytest.raises(CalendarAPIError):
        await plugin.fetch_document(doc)


# ── Malformed events ─────────────────────────────────────────────


def test_flatten_handles_missing_organizer():
    out = flatten_event_fields(
        {
            "id": "e1",
            "summary": "Solo time",
            "status": "confirmed",
            "start": {"dateTime": "2026-04-30T14:00:00Z"},
            "end": {"dateTime": "2026-04-30T15:00:00Z"},
        },
        calendar_id="primary",
    )
    assert out["organizer_email"] == ""
    assert out["organizer_name"] == ""


def test_flatten_handles_completely_empty_event():
    """An event with only an id (rare but possible on partial reads) shouldn't crash."""
    out = flatten_event_fields({"id": "e1"}, calendar_id="primary")
    assert out["summary"] == ""
    assert out["start"] == ""
    assert out["status"] == ""


def test_normalizer_handles_event_without_summary():
    raw = json.dumps(
        {
            "id": "e1",
            "status": "confirmed",
            "start": {"dateTime": "2026-04-30T14:00:00Z"},
            "end": {"dateTime": "2026-04-30T15:00:00Z"},
        }
    ).encode("utf-8")
    out = calendar_to_markdown(raw, {})
    assert "# (no title)" in out


def test_normalizer_handles_event_without_start_time():
    """An event with no time fields renders the heading and skips When."""
    raw = json.dumps({"id": "e1", "summary": "Open", "status": "confirmed"}).encode("utf-8")
    out = calendar_to_markdown(raw, {})
    assert "# Open" in out
    assert "**When:**" not in out


# ── List-time defensive paths ────────────────────────────────────


async def test_list_documents_skips_events_without_id():
    plugin, mock = _plugin()
    mock.list_events.return_value = {
        "items": [
            {"summary": "no id"},
            {
                "id": "e1",
                "summary": "ok",
                "status": "confirmed",
                "updated": "2026-04-15T09:21:33Z",
                "start": {"dateTime": "2026-04-30T14:00:00Z"},
                "end": {"dateTime": "2026-04-30T15:00:00Z"},
            },
        ]
    }
    refs = await plugin.list_documents()
    assert [r.source_id for r in refs] == ["e1"]


# ── Factory configuration paths ──────────────────────────────────


def test_factory_credentials_path_via_config_dict(tmp_path):
    from src.harvester.registry import create_plugin

    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    plugin, closeable = create_plugin(
        "calendar", {"credentials_path": str(creds)}
    )
    assert isinstance(plugin, GoogleCalendarHarvesterPlugin)
    assert closeable is None


def test_factory_custom_credentials_env_resolves(monkeypatch, tmp_path):
    from src.harvester.registry import create_plugin

    creds = tmp_path / "custom-creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("MY_CAL_CREDS", str(creds))
    monkeypatch.delenv("CALENDAR_CREDENTIALS_PATH", raising=False)
    plugin, _ = create_plugin("calendar", {"credentials_env": "MY_CAL_CREDS"})
    assert isinstance(plugin, GoogleCalendarHarvesterPlugin)


def test_factory_honours_past_future_days_overrides(monkeypatch, tmp_path):
    from src.harvester.registry import create_plugin

    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("CALENDAR_CREDENTIALS_PATH", str(creds))
    plugin, _ = create_plugin(
        "calendar", {"past_days": 30, "future_days": 7}
    )
    assert plugin.config.past_days == 30
    assert plugin.config.future_days == 7
