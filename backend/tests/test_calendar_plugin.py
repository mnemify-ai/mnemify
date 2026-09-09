"""Tests for :class:`src.harvester.calendar.plugin.GoogleCalendarHarvesterPlugin`.

Mirrors ``test_gmail_plugin.py``: scaffold invariants, SourcePlugin
contract assertions, factory roundtrip via the registry, and
per-method semantics with a mocked :class:`GoogleCalendarClient`.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.harvester import (
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from src.harvester.calendar import (
    CalendarConfig,
    GoogleCalendarHarvesterPlugin,
)
from src.harvester.calendar.client import (
    CalendarAuthError,
    GoogleCalendarClient,
)
from src.harvester.registry import create_plugin, registered_source_types


def _make_plugin() -> tuple[GoogleCalendarHarvesterPlugin, AsyncMock]:
    cfg = CalendarConfig()
    mock_client = AsyncMock(spec=GoogleCalendarClient)
    plugin = GoogleCalendarHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


def _event(
    event_id: str = "e1",
    *,
    summary: str = "Standup",
    status: str = "confirmed",
    updated: str = "2026-04-15T09:21:33.123Z",
    **extra,
) -> dict:
    base = {
        "id": event_id,
        "summary": summary,
        "status": status,
        "updated": updated,
        "htmlLink": f"https://www.google.com/calendar/event?eid={event_id}",
        "start": {"dateTime": "2026-04-30T14:00:00Z"},
        "end": {"dateTime": "2026-04-30T15:00:00Z"},
    }
    base.update(extra)
    return base


# ── Scaffold invariants ──────────────────────────────────────────


def test_calendar_module_importable():
    import src.harvester.calendar  # noqa: F401


def test_calendar_public_names_exported():
    from src.harvester import calendar as cal_mod

    for name in (
        "CalendarConfig",
        "GoogleCalendarClient",
        "CalendarAPIError",
        "CalendarAuthError",
        "EventExtractor",
        "GoogleCalendarHarvesterPlugin",
    ):
        assert hasattr(cal_mod, name), f"Expected {name!r} in src.harvester.calendar"


def test_calendar_registered_in_plugin_registry():
    assert "calendar" in registered_source_types()


def test_plugin_is_source_plugin_subclass():
    assert issubclass(GoogleCalendarHarvesterPlugin, SourcePlugin)


def test_plugin_source_type():
    cfg = CalendarConfig()
    plugin = GoogleCalendarHarvesterPlugin(cfg)
    assert plugin.SOURCE_TYPE == "calendar"


def test_factory_roundtrip_via_registry(monkeypatch, tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("CALENDAR_CREDENTIALS_PATH", str(creds))
    plugin, closeable = create_plugin("calendar", {})
    assert isinstance(plugin, GoogleCalendarHarvesterPlugin)
    assert closeable is None


def test_factory_raises_when_neither_env_nor_bundle_available(monkeypatch, tmp_path):
    from src.harvester._google import oauth as google_oauth

    monkeypatch.delenv("CALENDAR_CREDENTIALS_PATH", raising=False)
    bundle = tmp_path / "oauth_client.json"
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundle)
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("calendar", {})
    msg = str(excinfo.value)
    assert "CALENDAR_CREDENTIALS_PATH" in msg
    assert str(bundle) in msg


# ── test_connection contract ──────────────────────────────────────


async def test_test_connection_healthy_on_calendar_list_success():
    plugin, mock = _make_plugin()
    mock.get_calendar_list.return_value = {
        "items": [
            {"id": "primary", "summary": "Personal", "primary": True},
            {"id": "team", "summary": "Team Acme"},
        ]
    }
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy is True
    assert health.source_type == "calendar"
    assert health.details["calendar_count"] == 2
    assert health.details["primary"] == "Personal"


async def test_test_connection_unhealthy_on_auth_error():
    plugin, mock = _make_plugin()
    mock.get_calendar_list.side_effect = CalendarAuthError(
        "Unauthorized", status_code=401
    )
    health = await plugin.test_connection()
    assert health.healthy is False
    assert "mnemify login --source calendar" in health.message


async def test_test_connection_unhealthy_on_generic_error():
    plugin, mock = _make_plugin()
    mock.get_calendar_list.side_effect = RuntimeError("boom")
    health = await plugin.test_connection()
    assert health.healthy is False
    assert "boom" in health.message


# ── list_documents contract ──────────────────────────────────────


async def test_list_documents_emits_docrefs_with_event_metadata():
    plugin, mock = _make_plugin()
    mock.list_events.return_value = {
        "items": [_event("e1", summary="Standup"), _event("e2", summary="Demo")]
    }

    refs = await plugin.list_documents()

    assert len(refs) == 2
    assert all(isinstance(r, DocRef) for r in refs)
    first = refs[0]
    assert first.source_id == "e1"
    assert first.source_type == "calendar"
    assert first.title == "Standup"
    assert first.metadata["calendar_id"] == "primary"
    assert first.metadata["status"] == "confirmed"
    assert first.metadata["document_type"] == "event"
    assert first.modified_at is not None
    assert first.modified_at.year == 2026


async def test_list_documents_drops_cancelled_events_by_default():
    plugin, mock = _make_plugin()
    mock.list_events.return_value = {
        "items": [
            _event("e1", status="confirmed"),
            _event("e2", status="cancelled"),
        ]
    }

    refs = await plugin.list_documents()

    assert [r.source_id for r in refs] == ["e1"]


async def test_list_documents_includes_cancelled_when_show_deleted_set():
    cfg = CalendarConfig(show_deleted=True)
    mock_client = AsyncMock(spec=GoogleCalendarClient)
    plugin = GoogleCalendarHarvesterPlugin(cfg, client=mock_client)

    mock_client.list_events.return_value = {
        "items": [
            _event("e1", status="confirmed"),
            _event("e2", status="cancelled"),
        ]
    }

    refs = await plugin.list_documents()
    assert {r.source_id for r in refs} == {"e1", "e2"}


async def test_list_documents_passes_since_through_as_updated_min():
    plugin, mock = _make_plugin()
    mock.list_events.return_value = {"items": []}
    anchor = datetime(2026, 4, 22, 0, 0)

    await plugin.list_documents(since=anchor)

    call_kwargs = mock.list_events.await_args.kwargs
    assert call_kwargs.get("updated_min") == anchor


async def test_list_documents_iterates_all_configured_calendars():
    cfg = CalendarConfig(calendar_ids=["primary", "team@group.calendar.google.com"])
    mock_client = AsyncMock(spec=GoogleCalendarClient)
    plugin = GoogleCalendarHarvesterPlugin(cfg, client=mock_client)

    mock_client.list_events.return_value = {"items": [_event("e1")]}
    await plugin.list_documents()

    assert mock_client.list_events.await_count >= 2


# ── fetch_document contract ──────────────────────────────────────


async def test_fetch_document_returns_raw_document_with_format_json():
    plugin, mock = _make_plugin()
    mock.get_event.return_value = _event("e1", summary="Project kickoff")
    doc_ref = DocRef(
        source_id="e1",
        title="x",
        source_type="calendar",
        metadata={"calendar_id": "primary"},
    )

    raw = await plugin.fetch_document(doc_ref)

    assert isinstance(raw, RawDocument)
    assert raw.source_id == "e1"
    assert raw.format == "json"
    assert raw.title == "Project kickoff"
    parsed = json.loads(raw.content)
    assert parsed["id"] == "e1"


async def test_fetch_document_metadata_carries_required_keys():
    plugin, mock = _make_plugin()
    mock.get_event.return_value = _event(
        "e1",
        summary="Acme renewal",
        organizer={"email": "amy@acme.com", "displayName": "Amy"},
        attendees=[{"email": "bob@y.com"}],
        location="Conference Room B",
    )
    doc_ref = DocRef(
        source_id="e1",
        title="x",
        source_type="calendar",
        metadata={"calendar_id": "primary"},
    )

    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    assert md["document_type"] == "event"
    assert md["summary"] == "Acme renewal"
    assert md["organizer_email"] == "amy@acme.com"
    assert md["attendee_emails"] == ["bob@y.com"]
    assert md["location"] == "Conference Room B"


async def test_fetch_document_returns_empty_attachments_list():
    """Calendar attachments are Drive links — bytes are not downloaded here."""
    plugin, mock = _make_plugin()
    mock.get_event.return_value = _event(
        "e1",
        attachments=[{"title": "doc", "fileUrl": "https://drive.google.com/x"}],
    )
    doc_ref = DocRef(
        source_id="e1",
        title="x",
        source_type="calendar",
        metadata={"calendar_id": "primary"},
    )

    raw = await plugin.fetch_document(doc_ref)

    assert raw.attachments == []
    # But the count is still preserved in metadata so the compiler knows
    assert raw.metadata["attachment_count"] == 1


# ── normalize contract — pure body, no frontmatter ──────────────


def test_normalize_returns_pure_body_markdown():
    plugin, _mock = _make_plugin()
    raw = RawDocument(
        source_id="e1",
        title="Standup",
        content=json.dumps(_event("e1")).encode("utf-8"),
        format="json",
        metadata={"summary": "Standup"},
    )

    norm = plugin.normalize(raw)

    assert isinstance(norm, NormalizedDocument)
    assert norm.source_id == "e1"
    assert norm.frontmatter == {}
    assert not norm.markdown.startswith("---")
    assert norm.markdown.lstrip("\n").startswith("# ")
    assert norm.normalizer_version == "0.1.0"


# ── fetch_attachment is a deliberate not-implemented ──────────


async def test_fetch_attachment_raises_not_implemented():
    plugin, _mock = _make_plugin()
    from src.harvester import AttachmentRef

    att = AttachmentRef(
        source_id="e1",
        filename="x.pdf",
        url="https://drive.google.com/x",
    )
    with pytest.raises(NotImplementedError):
        await plugin.fetch_attachment(att)
