"""Google Calendar source plugin — implements :class:`SourcePlugin`.

Mirrors :class:`src.harvester.gmail.plugin.GoogleCalendarHarvesterPlugin`
in every respect except where the data shape forces a difference:

- ``test_connection`` probes ``calendarList.list`` (cheapest auth call).
- ``list_documents`` enumerates every event in the configured calendars
  inside the ``[now - past_days, now + future_days]`` window. The
  orchestrator's ``since`` parameter maps to ``updatedMin`` (incremental
  — only events whose record changed since the last harvest).
- ``fetch_document`` returns a :class:`RawDocument` with ``format="json"``
  carrying the full event envelope.
- ``fetch_attachment`` is a no-op for now — Calendar attachments are
  Google Drive links; downloading their bytes is the Drive plugin's
  concern. The metadata still surfaces them and the markdown body
  links them inline, but no bytes are fetched.
- ``normalize`` returns pure-body markdown; ``frontmatter={}``.

``mark_harvested`` is a deliberate no-op (read-only scope; we cannot
write back). ``aclose`` delegates to :class:`GoogleCalendarClient.aclose`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)

from .client import CalendarAPIError, CalendarAuthError, GoogleCalendarClient
from .events import EventExtractor
from .fields import flatten_event_fields
from .models import CalendarConfig
from .normalizer import calendar_to_markdown

logger = logging.getLogger(__name__)


def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse a Calendar-emitted ISO-8601 timestamp into a naive-UTC datetime.

    Mirrors the helper in :mod:`src.harvester.jira.plugin`. Calendar
    emits offsets like ``2026-04-15T09:21:33.123Z`` or
    ``2026-04-15T09:21:33.123-07:00``; both forms parse cleanly with
    :func:`datetime.fromisoformat` on Python 3.11+.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class GoogleCalendarHarvesterPlugin(SourcePlugin):
    """Google Calendar implementation of :class:`SourcePlugin`."""

    SOURCE_TYPE = "calendar"

    def __init__(
        self,
        config: CalendarConfig,
        *,
        client: GoogleCalendarClient | None = None,
    ) -> None:
        self.config = config
        if client is None:
            client = GoogleCalendarClient(
                credentials_path="",
                token_path=config.token_path,
            )
        self.client = client
        self.events = EventExtractor(self.client)

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Probe ``calendarList.list`` to verify the OAuth credentials work."""
        try:
            result = await self.client.get_calendar_list()
        except CalendarAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"Calendar authentication failed ({exc.status_code}). "
                    "Re-run `mnemify login --source calendar` to refresh the OAuth token."
                ),
            )
        except CalendarAPIError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Calendar API error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Connection failed: {exc}",
            )

        items = result.get("items") or []
        primary = next(
            (c.get("summary") or c.get("id") for c in items if c.get("primary")),
            None,
        )
        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"Connected to {len(items)} calendar(s); primary={primary or 'unknown'}",
            details={
                "calendar_count": len(items),
                "primary": primary,
            },
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """Enumerate events across the configured calendars as :class:`DocRef`.

        The harvest time window is ``[now - past_days, now + future_days]``
        (configurable on :class:`CalendarConfig`). The orchestrator's
        ``since`` is threaded through as ``updatedMin`` for incremental
        sync — events modified since the last run, regardless of when
        they're scheduled.
        """
        # Use timezone-aware UTC ``now``, then drop the tzinfo so the
        # resulting datetimes carry the same naive-UTC convention every
        # other plugin uses (DocRef.modified_at is naive UTC).
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        time_min = now - timedelta(days=self.config.past_days)
        time_max = now + timedelta(days=self.config.future_days)

        doc_refs: list[DocRef] = []
        for calendar_id in self.config.calendar_ids:
            async for event in self.events.list_events(
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                updated_min=since,
                max_events=self.config.max_events_per_run,
                show_deleted=self.config.show_deleted,
            ):
                ref = self._doc_ref_from_event(event, calendar_id)
                if ref is not None:
                    doc_refs.append(ref)
        return doc_refs

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch an event's full content as :class:`RawDocument` (format='json')."""
        calendar_id = doc_ref.metadata.get("calendar_id") or "primary"
        event = await self.events.get_full_event(calendar_id, doc_ref.source_id)

        content = json.dumps(event, ensure_ascii=False).encode("utf-8")
        metadata = flatten_event_fields(event, calendar_id=calendar_id)

        title = metadata.get("summary") or doc_ref.title or "(no title)"

        return RawDocument(
            source_id=event.get("id") or doc_ref.source_id,
            title=title,
            content=content,
            format="json",
            metadata=metadata,
            attachments=[],  # Drive attachments tracked in metadata only — see module docstring
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Calendar attachments are Drive URLs — not downloaded by this plugin.

        Provided for ABC contract conformance. The orchestrator never
        calls this in practice because :meth:`fetch_document` returns an
        empty ``attachments`` list.
        """
        raise NotImplementedError(
            "Calendar attachments are Google Drive links; download them via "
            "the Drive plugin once it lands."
        )

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert event JSON to pure-body markdown — no frontmatter."""
        markdown = calendar_to_markdown(raw.content, raw.metadata)
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=markdown,
            frontmatter={},
            normalizer_version="0.1.0",
        )

    async def aclose(self) -> None:
        """Release the underlying :class:`GoogleCalendarClient` (best-effort)."""
        await self.client.aclose()

    # ── Internal helpers ──────────────────────────────────────────

    def _doc_ref_from_event(self, event: dict, calendar_id: str) -> DocRef | None:
        """Project a list-endpoint event dict into a :class:`DocRef`.

        Skips events without an ``id`` (defensive — without a stable id
        they can't be re-fetched). Skips cancelled events when
        ``show_deleted`` is False — Google sometimes returns them in
        ``events.list`` results (e.g. instances of a recurring meeting
        the user dismissed once) even though they're marked cancelled.
        """
        event_id = event.get("id")
        if not event_id:
            return None
        if event.get("status") == "cancelled" and not self.config.show_deleted:
            return None

        summary = event.get("summary") or "(no title)"
        modified_at = _parse_iso_utc(event.get("updated"))

        return DocRef(
            source_id=event_id,
            title=summary,
            source_type=self.SOURCE_TYPE,
            source_url=event.get("htmlLink"),
            modified_at=modified_at,
            metadata={
                "document_type": "event",
                "calendar_id": calendar_id,
                "summary": summary,
                "status": event.get("status"),
            },
        )
