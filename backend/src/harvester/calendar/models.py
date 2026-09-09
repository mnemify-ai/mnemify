"""Google Calendar plugin data models.

Mirrors :mod:`src.harvester.gmail.models`. The only Calendar-specific
fields are the time-window tuning knobs (``past_days`` / ``future_days``)
because Calendar is unique among harvested sources in that *future*
events have value too — the compiler wants to know what's coming up,
not just what already happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CalendarConfig:
    """Configuration for the Google Calendar harvester.

    Matches the ``sources.calendar`` block of ``mnemify.yaml`` 1:1.

    Attributes:
        credentials_env: Power-user override — name of the env var that
            holds the absolute path to a custom Google OAuth client-secret
            JSON file. Most users leave this alone; the harvester falls
            back to the Mnemify-shipped OAuth client at
            ``backend/src/harvester/_google/oauth_client.json``. The same
            client config is shared with Gmail and any other Google
            service plugin.
        token_path: Path to the cached refresh-token JSON written by
            ``mnemify login --source calendar`` on first authorisation.
            ``~``-expansion is honoured at load time. Default groups
            Calendar's token next to other Google service tokens (Gmail,
            Drive, ...) so they share one OS-level directory.
        calendar_ids: Calendars to enumerate. Defaults to ``["primary"]``
            — the user's main calendar. Add additional IDs (e.g. shared
            team calendars, secondary personal calendars) as needed.
        past_days: Lower bound of the harvest window, in days back from
            now. ``timeMin`` of ``events.list`` is set accordingly.
        future_days: Upper bound of the harvest window, in days ahead of
            now. ``timeMax`` of ``events.list`` is set accordingly.
            Future events have value for "what's coming up" context.
        show_deleted: Whether to include cancelled events. Default False
            — most users don't want declined / removed meetings cluttering
            the manifest, but turning it on lets the compiler see "Amy
            cancelled the renewal call last week" patterns.
        max_events_per_run: Optional safety cap. ``None`` runs unbounded;
            useful for first runs against a busy calendar where you want
            to sample 200 events before committing to the full window.
        concurrency: Per-source concurrency override; defaults to 3 to
            match the other API-bound plugins.
    """

    credentials_env: str = "CALENDAR_CREDENTIALS_PATH"
    token_path: str = "~/.mnemify/google/calendar-token.json"
    calendar_ids: list[str] = field(default_factory=lambda: ["primary"])
    past_days: int = 90
    future_days: int = 90
    show_deleted: bool = False
    max_events_per_run: int | None = None
    concurrency: int = 3
