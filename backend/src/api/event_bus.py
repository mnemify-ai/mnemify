"""In-memory pub/sub for harvest progress events.

Single-process, single-user — no broker needed. Each SSE subscriber
gets its own asyncio.Queue; publishers fan out. Dropped events on
backpressure are fine for this use case (the UI only needs fresh data).

A bounded replay buffer keeps the most recent events so a UI tab that
connects *after* a (fast) source has already finished still sees its
log lines and per-source ``source_complete`` markers — without this,
an Obsidian harvest that completes in <1 s before the SSE stream opens
would be invisible. The buffer is reset at the start of each fresh run.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, AsyncIterator


# Per-subscriber queue depth. Progress events are frequent; if a reader
# lags past this, we drop (the next event is almost here).
PER_SUB_CAPACITY = 512
# How many recent events to retain for replay to late subscribers. One
# event per harvested doc + a handful of progress/log/error frames, so a
# few thousand covers any realistic single run; older frames age out.
REPLAY_BUFFER_CAP = 2000


class EventBus:
    def __init__(
        self,
        per_sub_capacity: int = PER_SUB_CAPACITY,
        replay_cap: int = REPLAY_BUFFER_CAP,
    ) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._capacity = per_sub_capacity
        self._lock = asyncio.Lock()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=replay_cap)

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._capacity)
        async with self._lock:
            self._subs.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        """Fire-and-forget — callable from sync contexts (inside plugin code)."""
        self._buffer.append(event)
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop — downstream reader is lagging. Progress events are
                # frequent; the next one is almost here.
                pass

    def replay(self) -> list[dict[str, Any]]:
        """Snapshot of the recent-events buffer, oldest first.

        Yielded to a new subscriber right after the ``snapshot`` frame so a
        late-joining UI catches events it missed (notably fast sources).
        """
        return list(self._buffer)

    def reset_buffer(self) -> None:
        """Clear the replay buffer — call at the start of a fresh run (and on
        a harvest-data reset) so stale log lines aren't replayed into a new
        run's stream."""
        self._buffer.clear()

    async def iter_events(self, q: asyncio.Queue) -> AsyncIterator[dict]:
        while True:
            event = await q.get()
            yield event


# Module-level singleton — one harvest at a time, one bus.
bus = EventBus()
