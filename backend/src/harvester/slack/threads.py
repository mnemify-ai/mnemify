"""Message extractor — channel walks, thread reads, day-window grouping.

All four entry points are async iterators / coroutines that hit the
:class:`SlackClient` and return parsed message dicts. Callers (the
plugin) shape the output into ``DocRef`` / ``RawDocument`` envelopes.

Slack pagination convention: every list endpoint returns a
``response_metadata.next_cursor`` string; the next call passes it back
as ``cursor=…``. An empty/absent cursor means "you've walked the whole
thing." We dedup on ``ts`` per channel-walk because Slack occasionally
re-yields the same page when called during a write burst — defensive
against a known correctness rough edge.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone

from .client import SlackClient

logger = logging.getLogger(__name__)


def _ts_to_datetime(ts_str: str) -> datetime:
    """Slack ts is a string like ``"1700000000.123456"`` — Unix epoch seconds."""
    try:
        return datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _effective_modified_ts(msg: dict) -> str:
    """Return ``max(ts, edited.ts)`` so incrementals catch in-place edits."""
    ts = msg.get("ts", "0")
    edited = (msg.get("edited") or {}).get("ts")
    if edited and edited > ts:
        return edited
    return ts


class MessageExtractor:
    """Async helpers around the :class:`SlackClient` for the plugin's use."""

    def __init__(self, client: SlackClient) -> None:
        self._client = client

    # ── Thread enumeration ────────────────────────────────────────

    async def list_thread_starters(
        self,
        channel_id: str,
        *,
        oldest: float | None = None,
    ) -> AsyncIterator[dict]:
        """Yield every top-level message in a channel: thread roots and standalone.

        A "top-level" message is one whose ``thread_ts`` is missing or
        equals its own ``ts`` — i.e. it's the start of a thread or a
        message with no replies. Reply messages (``thread_ts != ts``)
        are skipped because they're picked up via ``get_thread`` when
        the plugin fetches the parent.

        ``oldest`` is a Unix epoch float (Slack's native filter format).
        """
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = await self._client.conversations_history(
                channel_id, oldest=oldest, cursor=cursor, limit=200,
            )
            for msg in page.get("messages", []) or []:
                ts = msg.get("ts")
                if not ts or ts in seen:
                    continue
                seen.add(ts)
                thread_ts = msg.get("thread_ts")
                if thread_ts and thread_ts != ts:
                    # This is a *reply* surfaced in history — skip; the parent
                    # walk will pull it via conversations.replies.
                    continue
                yield msg
            if not page.get("has_more"):
                break
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break

    async def get_thread(self, channel_id: str, thread_ts: str) -> list[dict]:
        """Return the full message list for one thread (parent + all replies)."""
        all_messages: list[dict] = []
        cursor: str | None = None
        while True:
            page = await self._client.conversations_replies(
                channel_id, thread_ts, cursor=cursor, limit=200,
            )
            all_messages.extend(page.get("messages", []) or [])
            if not page.get("has_more"):
                break
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        return all_messages

    # ── Day-summary mode ──────────────────────────────────────────

    async def list_messages_in_day(
        self,
        channel_id: str,
        day: date,
    ) -> list[dict]:
        """All messages (top-level + replies surfaced as separate items)
        whose ``ts`` falls inside the UTC day window ``[day, day+1)``.

        Used by ``channel_summary`` mode — one doc per channel-day.
        Includes replies inline in chronological order (no thread
        nesting) because the summary is already a "what happened this
        day" view, not a thread index.
        """
        oldest = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        latest = (
            datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(days=1)
        ).timestamp()
        out: list[dict] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = await self._client.conversations_history(
                channel_id,
                oldest=oldest,
                latest=latest,
                cursor=cursor,
                limit=200,
            )
            for msg in page.get("messages", []) or []:
                ts = msg.get("ts")
                if not ts or ts in seen:
                    continue
                seen.add(ts)
                out.append(msg)
            if not page.get("has_more"):
                break
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        # Sort ascending — Slack returns newest-first, but readers expect chronological.
        out.sort(key=lambda m: float(m.get("ts", "0") or "0"))
        return out

    async def list_active_days(
        self,
        channel_id: str,
        *,
        oldest: float | None = None,
    ) -> list[date]:
        """Return the sorted list of UTC days in which the channel had any
        message at all.

        This is the driver for ``channel_summary`` mode: emit one
        ``DocRef`` per active day rather than one per day-of-the-year.
        """
        days: set[date] = set()
        cursor: str | None = None
        while True:
            page = await self._client.conversations_history(
                channel_id, oldest=oldest, cursor=cursor, limit=200,
            )
            for msg in page.get("messages", []) or []:
                ts = msg.get("ts")
                if not ts:
                    continue
                days.add(_ts_to_datetime(ts).date())
            if not page.get("has_more"):
                break
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        return sorted(days)
