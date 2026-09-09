"""Shared SSE helpers for the harvest + terrain event streams."""

from __future__ import annotations

import json
from typing import Any


def _json(obj: Any) -> str:
    """Serialise an event payload for an SSE ``data:`` line.

    ``default=str`` so the odd datetime / Path / non-trivial value that
    sneaks into an event dict degrades to its string form instead of
    breaking the whole stream.
    """
    return json.dumps(obj, default=str)
