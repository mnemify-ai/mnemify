"""EventExtractor — iterate a calendar's events via the Calendar v3 API.

Mirrors :class:`src.harvester.gmail.threads.ThreadExtractor`: a thin
adapter over :class:`GoogleCalendarClient` that owns pagination and
the optional safety cap. Higher-level concerns (DocRef assembly,
metadata flattening, normalisation) live in
:class:`GoogleCalendarHarvesterPlugin`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime

from .client import GoogleCalendarClient

logger = logging.getLogger(__name__)


class EventExtractor:
    """Walk a calendar's events and produce raw event dicts."""

    def __init__(self, client: GoogleCalendarClient) -> None:
        self.client = client

    async def list_events(
        self,
        *,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        updated_min: datetime | None = None,
        max_events: int | None = None,
        page_size: int = 250,
        show_deleted: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield event dicts in the ``[time_min, time_max]`` window.

        ``updated_min`` is the orchestrator's incremental anchor —
        events whose record was modified since that timestamp. The time
        window itself filters by *event* time and is independent of the
        update timestamp.

        Stops on absent ``nextPageToken``, on the defensive empty-page
        break (a degenerate response with empty ``items`` plus a
        non-None token can't loop forever), or once ``max_events`` items
        have been yielded — whichever comes first.
        """
        page_token: str | None = None
        yielded = 0
        while True:
            page = await self.client.list_events(
                calendar_id,
                time_min=time_min,
                time_max=time_max,
                updated_min=updated_min,
                page_token=page_token,
                max_results=page_size,
                show_deleted=show_deleted,
            )
            items = page.get("items") or []
            if not items:
                return

            for event in items:
                yield event
                yielded += 1
                if max_events is not None and yielded >= max_events:
                    return

            page_token = page.get("nextPageToken")
            if not page_token:
                return

    async def get_full_event(self, calendar_id: str, event_id: str) -> dict:
        """Fetch the full payload for a single event."""
        return await self.client.get_event(calendar_id, event_id)
