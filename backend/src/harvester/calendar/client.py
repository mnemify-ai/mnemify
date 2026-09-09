"""Low-level Google Calendar API client — async facade over googleapiclient.

Mirrors :mod:`src.harvester.gmail.client`: the underlying
``google-api-python-client`` is synchronous, so every public method
here wraps the sync call in ``asyncio.to_thread(...)`` and applies a
tenacity retry decorator that handles 429/5xx with ``Retry-After``
awareness.

Typed exceptions:

- :class:`CalendarAPIError` — generic non-2xx wrapper.
- :class:`CalendarAuthError` (subclass) — 401 / 403, terminal.
- :class:`_RetryableCalendarError` (internal subclass) — 429 / 5xx, retryable.

The retry / classification helpers are duplicated verbatim from
``gmail/client.py``. A future refactor could lift them into
``_google/http.py`` once a third Google plugin lands; for two plugins
the duplication is small enough that the indirection isn't worth it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .auth import load_credentials

logger = logging.getLogger(__name__)


# ── Typed errors ──────────────────────────────────────────────────


class CalendarAPIError(Exception):
    """Raised when the Calendar REST API returns a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CalendarAuthError(CalendarAPIError):
    """Raised on 401/403 responses from the Calendar API.

    Surfaced separately so the plugin can translate it into a
    :class:`HealthStatus` with a clear remediation pointer at
    ``mnemify login --source calendar``.
    """


class _RetryableCalendarError(CalendarAPIError):
    """Internal: marks a 429 or 5xx response as tenacity-retryable."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


# ── Retry helpers ─────────────────────────────────────────────────

_MAX_RETRY_AFTER_SECONDS = 60.0
_MAX_ATTEMPTS = 5


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value))
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, _RetryableCalendarError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _classify_http_error(exc: Any) -> CalendarAPIError:
    """Translate a ``googleapiclient.errors.HttpError`` into our typed set."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None) if resp is not None else None
    message = f"Calendar API error (status={status}): {exc}"

    if status in (401, 403):
        return CalendarAuthError(message, status_code=status)
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        retry_after = None
        if resp is not None:
            try:
                retry_after = _parse_retry_after(resp.get("retry-after"))
            except Exception:  # noqa: BLE001 — header lookup must not raise
                retry_after = None
        return _RetryableCalendarError(message, status_code=status, retry_after=retry_after)
    return CalendarAPIError(message, status_code=status)


def _with_retry(fn):
    return retry(
        retry=retry_if_exception_type(_RetryableCalendarError),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_retry_wait,
        reraise=True,
    )(fn)


# ── Client ────────────────────────────────────────────────────────


class GoogleCalendarClient:
    """Async facade over ``googleapiclient.discovery.build("calendar", "v3")``.

    Service object built lazily so tests can instantiate without OAuth.
    """

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None

    def _get_service(self):
        """Return the underlying Calendar service, building it on demand."""
        if self._service is None:
            from googleapiclient.discovery import build

            creds = load_credentials(
                self._token_path,
                client_secrets_path=self._credentials_path or None,
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    # ── Public async API ──────────────────────────────────────────

    async def get_calendar_list(self) -> dict:
        """List the calendars the authenticated user has access to.

        ``calendarList.list`` is the cheapest Calendar call that
        exercises the access token — used by
        :meth:`GoogleCalendarHarvesterPlugin.test_connection` as the
        canonical auth-probe endpoint.
        """
        return await asyncio.to_thread(self._get_calendar_list_sync)

    @_with_retry
    def _get_calendar_list_sync(self) -> dict:
        service = self._get_service()
        try:
            return service.calendarList().list().execute()
        except Exception as exc:
            raise _classify_http_error(exc) from exc

    async def list_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        updated_min: datetime | None = None,
        page_token: str | None = None,
        max_results: int = 250,
        show_deleted: bool = False,
    ) -> dict:
        """Run an event search via ``events.list``.

        Always passes ``singleEvents=True`` (recurring events expanded
        into instances — one harvested document per meeting instance)
        and ``orderBy="startTime"`` (so pagination produces a stable,
        chronological walk).
        """
        return await asyncio.to_thread(
            self._list_events_sync,
            calendar_id,
            time_min,
            time_max,
            updated_min,
            page_token,
            max_results,
            show_deleted,
        )

    @_with_retry
    def _list_events_sync(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        updated_min: datetime | None,
        page_token: str | None,
        max_results: int,
        show_deleted: bool,
    ) -> dict:
        service = self._get_service()
        # The Calendar API expects RFC3339 timestamps with timezone
        # designator. Naive datetimes are assumed UTC; aware datetimes
        # are converted to UTC before serialization.
        params: dict = {
            "calendarId": calendar_id,
            "timeMin": _to_rfc3339(time_min),
            "timeMax": _to_rfc3339(time_max),
            "singleEvents": True,
            "orderBy": "startTime",
            "showDeleted": show_deleted,
            "maxResults": max_results,
        }
        if updated_min is not None:
            params["updatedMin"] = _to_rfc3339(updated_min)
        if page_token is not None:
            params["pageToken"] = page_token

        try:
            return service.events().list(**params).execute()
        except Exception as exc:
            raise _classify_http_error(exc) from exc

    async def get_event(self, calendar_id: str, event_id: str) -> dict:
        """Fetch a single event by ID with the full payload."""
        return await asyncio.to_thread(self._get_event_sync, calendar_id, event_id)

    @_with_retry
    def _get_event_sync(self, calendar_id: str, event_id: str) -> dict:
        service = self._get_service()
        try:
            return (
                service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
        except Exception as exc:
            raise _classify_http_error(exc) from exc

    async def aclose(self) -> None:
        """Release any client-owned resources (best-effort).

        ``googleapiclient`` holds its own httplib2 Http instance with no
        async-aware close; the underlying socket is freed when the
        service is garbage-collected. Provided for symmetry with
        :class:`JiraClient.aclose` / :class:`GmailClient.aclose`.
        """
        self._service = None


def _to_rfc3339(dt: datetime) -> str:
    """Render a datetime as an RFC3339 string (UTC, ``Z`` suffix).

    Naive datetimes are assumed UTC. Timezone-aware datetimes are
    converted to UTC. Both forms produce ``YYYY-MM-DDTHH:MM:SSZ`` so
    Google's parser doesn't have to disambiguate.
    """
    from datetime import timezone

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
