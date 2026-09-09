"""Google Calendar source plugin — public API and registry self-registration.

Reuses the bundled OAuth client established for Gmail
(``backend/src/harvester/_google/oauth_client.json``); the same Google
Cloud project hosts both APIs. Operator setup on top of Gmail's is one
step: enable the Google Calendar API in the same project and add the
``calendar.readonly`` scope to the consent screen.

Output-format contract: pure-body markdown (Confluence/Gmail pattern).
All metadata flows through :attr:`RawDocument.metadata` to the
manifest's ``documents.metadata`` JSON column. The .md file's first
line is ``# {summary}``; never ``---``.
"""

from __future__ import annotations

from .client import (
    CalendarAPIError,
    CalendarAuthError,
    GoogleCalendarClient,
)
from .events import EventExtractor
from .models import CalendarConfig
from .plugin import GoogleCalendarHarvesterPlugin

__all__ = [
    # Models
    "CalendarConfig",
    # Client + extractors
    "GoogleCalendarClient",
    "CalendarAPIError",
    "CalendarAuthError",
    "EventExtractor",
    # Plugin
    "GoogleCalendarHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_calendar_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.calendar`` sub-dict from mnemify.yaml
    (or a programmatic dict matching :class:`CalendarConfig`). Returns
    ``(plugin, None)`` — ``googleapiclient`` is synchronous and has no
    async resource to pump; teardown lives in ``plugin.aclose()``.

    OAuth client resolution (delegated to
    :func:`src.harvester._google.oauth.resolve_client_secrets_path`):

    1. ``credentials_path`` directly in the YAML config.
    2. The env var named by ``credentials_env`` — power-user override.
    3. The bundled Mnemify OAuth client (the typical path).

    Raises :class:`EnvironmentError` only when *all three* are absent.
    """
    from src.harvester._google.oauth import resolve_client_secrets_path

    cfg = CalendarConfig(
        credentials_env=config.get("credentials_env", "CALENDAR_CREDENTIALS_PATH"),
        token_path=config.get(
            "token_path", "~/.mnemify/google/calendar-token.json"
        ),
        calendar_ids=list(config.get("calendar_ids", ["primary"]) or ["primary"]),
        past_days=int(config.get("past_days", 90)),
        future_days=int(config.get("future_days", 90)),
        show_deleted=bool(config.get("show_deleted", False)),
        max_events_per_run=config.get("max_events_per_run"),
        concurrency=config.get("concurrency", 3),
    )

    explicit_path = config.get("credentials_path")
    resolved = resolve_client_secrets_path(
        client_secrets_path=explicit_path,
        client_secrets_env=cfg.credentials_env,
    )

    client = GoogleCalendarClient(
        credentials_path=str(resolved),
        token_path=cfg.token_path,
    )
    plugin = GoogleCalendarHarvesterPlugin(cfg, client=client)
    return plugin, None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("calendar", _create_calendar_plugin)
