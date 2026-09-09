"""Event bus for the compile-progress SSE stream.

A separate ``EventBus`` instance from the harvest one (`event_bus.bus`) so the
two streams don't share a replay buffer or fan out into each other.
"""

from __future__ import annotations

from .event_bus import EventBus

compile_bus = EventBus()
