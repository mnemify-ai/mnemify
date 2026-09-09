"""Low-level Slack API client — async facade over the sync ``slack_sdk.WebClient``.

Mirrors the Jira plugin's ``client.py`` shape: synchronous third-party
client wrapped in ``asyncio.to_thread``, protected by a tenacity retry
decorator that honours Slack's ``Retry-After`` rate-limit header.

Why sync ``WebClient`` and not ``AsyncWebClient``? ``AsyncWebClient``
requires ``aiohttp``; pulling that in would put a second async HTTP
stack alongside the existing ``httpx`` one. The sync wrapping is also
how the Jira plugin handles ``atlassian-python-api`` — single pattern
across plugins.

Private file downloads (Slack's ``url_private``) require the
``Authorization: Bearer xoxp-…`` header. ``slack_sdk`` doesn't help
with these so the client holds a separate ``httpx.AsyncClient`` for
that one job.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── Typed errors ──────────────────────────────────────────────────


class SlackAPIError(Exception):
    """Raised when the Slack Web API returns an error response.

    Carries the Slack ``error`` code (e.g. ``"channel_not_found"``,
    ``"ratelimited"``) so callers can discriminate without parsing
    the underlying ``SlackApiError``.
    """

    def __init__(self, message: str, slack_error: str | None = None) -> None:
        super().__init__(message)
        self.slack_error = slack_error


class SlackAuthError(SlackAPIError):
    """Raised on auth-failure Slack error codes.

    Codes covered: ``invalid_auth``, ``not_authed``, ``token_revoked``,
    ``token_expired``, ``account_inactive``. Surfaced separately so the
    plugin can translate to a clear remediation message in ``HealthStatus``.
    """


class _RetryableSlackError(SlackAPIError):
    """Internal: marks a retryable Slack error (rate-limited or 5xx).

    Carries an optional ``retry_after`` (seconds) lifted from the
    ``Retry-After`` response header. Subclasses :class:`SlackAPIError`
    so a retry-exhausted failure still surfaces as :class:`SlackAPIError`.
    """

    def __init__(
        self,
        message: str,
        slack_error: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, slack_error=slack_error)
        self.retry_after = retry_after


_AUTH_ERRORS = frozenset({
    "invalid_auth",
    "not_authed",
    "token_revoked",
    "token_expired",
    "account_inactive",
    "missing_scope",
    "no_permission",
})


# ── Retry helpers ─────────────────────────────────────────────────

_MAX_RETRY_AFTER_SECONDS = 60.0
_MAX_ATTEMPTS = 5


def _parse_retry_after(value: Any) -> float | None:
    """Parse a ``Retry-After`` header value as seconds (numeric only)."""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Tenacity ``wait`` callable: honour ``Retry-After`` when present."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, _RetryableSlackError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _classify_slack_error(exc: SlackApiError) -> SlackAPIError:
    """Translate a ``SlackApiError`` into our typed exception set.

    - Auth errors → :class:`SlackAuthError` (terminal).
    - ``ratelimited`` or HTTP 5xx → :class:`_RetryableSlackError` with
      ``Retry-After`` lifted off the response headers when available.
    - else → :class:`SlackAPIError` (terminal).
    """
    error_code = ""
    headers: dict[str, Any] = {}
    status_code: int | None = None
    if exc.response is not None:
        try:
            error_code = exc.response.get("error", "") or ""
        except (AttributeError, TypeError):
            error_code = ""
        headers = dict(getattr(exc.response, "headers", {}) or {})
        status_code = getattr(exc.response, "status_code", None)

    message = f"Slack API error (code={error_code or '?'}, status={status_code}): {exc}"

    if error_code in _AUTH_ERRORS:
        return SlackAuthError(message, slack_error=error_code)
    if error_code == "ratelimited" or status_code == 429 or (
        status_code is not None and 500 <= status_code < 600
    ):
        retry_after = _parse_retry_after(headers.get("Retry-After"))
        return _RetryableSlackError(message, slack_error=error_code, retry_after=retry_after)
    return SlackAPIError(message, slack_error=error_code)


def _with_retry(fn):
    """Decorator applying the Slack retry policy to an async callable."""
    return retry(
        retry=retry_if_exception_type(_RetryableSlackError),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_retry_wait,
        reraise=True,
    )(fn)


# ── Client ────────────────────────────────────────────────────────


class SlackClient:
    """Async facade over ``slack_sdk.WebClient``.

    All public methods are coroutines that wrap the synchronous Slack
    SDK calls in ``asyncio.to_thread`` and apply the tenacity retry
    decorator. ``download_file`` uses a separate ``httpx.AsyncClient``
    because Slack's ``url_private`` endpoints are not part of the
    Web API surface and need raw bearer-auth HTTP.
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._sync: WebClient | None = None
        self._http: httpx.AsyncClient | None = None

    def _get_sync(self) -> WebClient:
        if self._sync is None:
            self._sync = WebClient(token=self._token)
        return self._sync

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=30.0,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        return self._http

    async def aclose(self) -> None:
        """Release the httpx client. The sync ``WebClient`` has no resource to close."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── Auth + workspace ──────────────────────────────────────────

    @_with_retry
    async def auth_test(self) -> dict[str, Any]:
        """Return the authenticated user/team identity. Cheap auth probe."""
        try:
            resp = await asyncio.to_thread(self._get_sync().auth_test)
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data

    @_with_retry
    async def team_info(self) -> dict[str, Any]:
        """Return ``team.info`` payload (workspace name, domain, icon)."""
        try:
            resp = await asyncio.to_thread(self._get_sync().team_info)
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data.get("team", {})

    # ── Conversations ─────────────────────────────────────────────

    @_with_retry
    async def conversations_info(self, channel_id: str) -> dict[str, Any]:
        try:
            resp = await asyncio.to_thread(
                self._get_sync().conversations_info,
                channel=channel_id,
            )
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data.get("channel", {})

    @_with_retry
    async def conversations_history(
        self,
        channel_id: str,
        *,
        oldest: float | None = None,
        latest: float | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Single page of channel history. Caller paginates via ``response_metadata.next_cursor``."""
        kwargs: dict[str, Any] = {"channel": channel_id, "limit": limit}
        if oldest is not None:
            kwargs["oldest"] = str(oldest)
        if latest is not None:
            kwargs["latest"] = str(latest)
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = await asyncio.to_thread(
                self._get_sync().conversations_history, **kwargs
            )
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data

    @_with_retry
    async def conversations_replies(
        self,
        channel_id: str,
        thread_ts: str,
        *,
        cursor: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"channel": channel_id, "ts": thread_ts, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = await asyncio.to_thread(
                self._get_sync().conversations_replies, **kwargs
            )
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data

    # ── Users ─────────────────────────────────────────────────────

    @_with_retry
    async def users_info(self, user_id: str, *, team_id: str | None = None) -> dict[str, Any]:
        """Resolve a user ID to a user object. Pass ``team_id`` for Slack Connect cross-team mentions."""
        kwargs: dict[str, Any] = {"user": user_id}
        if team_id:
            # Slack accepts include_locale and team_id for cross-team lookups.
            kwargs["team_id"] = team_id
        try:
            resp = await asyncio.to_thread(self._get_sync().users_info, **kwargs)
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data.get("user", {})

    @_with_retry
    async def users_list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = await asyncio.to_thread(self._get_sync().users_list, **kwargs)
        except SlackApiError as exc:
            raise _classify_slack_error(exc) from exc
        return resp.data

    # ── Files ─────────────────────────────────────────────────────

    async def download_file(self, url_private: str) -> bytes:
        """Download a private file via raw HTTP with the user token as bearer.

        Slack file URLs are not part of the Web API and need explicit
        ``Authorization: Bearer xoxp-…``. Returns ``b""`` on 404
        (tombstoned file) and warn-logs; raises :class:`SlackAPIError`
        on other non-2xx so the orchestrator's per-attachment try/except
        can record the failure without aborting the harvest.
        """
        try:
            resp = await self._get_http().get(url_private)
        except httpx.HTTPError as exc:
            raise SlackAPIError(f"file download failed for {url_private}: {exc}") from exc
        if resp.status_code == 404:
            logger.warning("Slack file 404 (tombstoned?) %s", url_private)
            return b""
        if resp.status_code >= 400:
            raise SlackAPIError(
                f"file download HTTP {resp.status_code} for {url_private}"
            )
        return resp.content
