"""Cumulative rate tracker shared by the harvest + compile orchestrators.

Each ``tick()`` records an event; after a short warm-up we report the
lifetime average ``count / elapsed`` and the UI turns it into an ETA.

Why cumulative, not the old 3-second sliding window? Notion pages and
LLM enrich calls are wildly non-uniform — small/cached items flush
through quickly, then a heavy one takes 10×+ longer. A sliding window
inflates the rate during a burst of cheap work, then either collapses
to "calculating…" the moment a heavy event evicts the burst or — worse
— reports a rate that under-estimates remaining wall-time. The lifetime
average absorbs the heavy events instead of forgetting them.
"""

from __future__ import annotations

import time

# Wait this many events before reporting a rate. Nine is enough that
# the first few small/cheap docs can't dominate the initial estimate —
# at three the ETA visibly swung 3×–9× while a heavy Notion page was
# still loading. Tradeoff: the bar reads "calculating…" longer at the
# start of small runs.
WARMUP_EVENTS = 6


class _Rate:
    """events/sec averaged over the whole run; ``None`` while warming up.

    Returns ``None`` until ≥ ``warmup_events`` events have ticked and the
    span from the first tick is ≥ 0.2 s. The UI renders that as
    "calculating…", which beats a misleading first-event rate.
    """

    def __init__(self, warmup_events: int = WARMUP_EVENTS) -> None:
        self.warmup_events = warmup_events
        self.count = 0
        self._first: float | None = None

    def tick(self) -> float | None:
        now = time.monotonic()
        if self._first is None:
            self._first = now
        self.count += 1
        if self.count < self.warmup_events:
            return None
        span = now - self._first
        if span < 0.2:
            return None
        return self.count / span


class _BytesRate:
    """bytes/sec averaged over the whole run; ``None`` while warming up.

    Companion to ``_Rate`` for Notion's bytes-weighted ETA overlay —
    block-paginated pages produce far more bytes than thin pages, so
    bytes/sec is a steadier proxy for true throughput than docs/sec.
    """

    def __init__(self, warmup_events: int = WARMUP_EVENTS) -> None:
        self.warmup_events = warmup_events
        self.count = 0
        self.total_bytes = 0
        self._first: float | None = None

    def tick(self, n_bytes: int) -> float | None:
        now = time.monotonic()
        if self._first is None:
            self._first = now
        self.count += 1
        self.total_bytes += max(0, int(n_bytes))
        if self.count < self.warmup_events:
            return None
        span = now - self._first
        if span < 0.2:
            return None
        return self.total_bytes / span
