"""Low-level Gmail API client — async facade over googleapiclient.

Mirrors :mod:`src.harvester.jira.client`: the underlying
``google-api-python-client`` is synchronous, so every public method here
wraps the sync call in ``asyncio.to_thread(...)`` and applies a tenacity
retry decorator that handles 429/5xx with ``Retry-After`` awareness.

Typed exceptions:

- :class:`GmailAPIError` — generic non-2xx wrapper.
- :class:`GmailAuthError` (subclass) — 401 / 403, terminal.
- :class:`_RetryableGmailError` (internal subclass) — 429 / 5xx, retryable.
"""

from __future__ import annotations

import asyncio
import logging
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


class GmailAPIError(Exception):
    """Raised when the Gmail REST API returns a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GmailAuthError(GmailAPIError):
    """Raised on 401/403 responses from the Gmail API.

    Surfaced separately so the plugin can translate it into a
    :class:`HealthStatus` with a clear remediation pointer at
    ``mnemify login --source gmail``.
    """


class _RetryableGmailError(GmailAPIError):
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

# Mirrors src/harvester/jira/client.py: cap server-suggested back-off so a
# misconfigured Retry-After cannot hang the harvest, and stop after 5 tries.
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
    if isinstance(exc, _RetryableGmailError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _classify_http_error(exc: Any) -> GmailAPIError:
    """Translate a ``googleapiclient.errors.HttpError`` into our typed set.

    ``googleapiclient`` exposes ``error.resp.status`` and ``error.resp``
    is a dict-like object (httplib2 Response); ``Retry-After`` lives at
    ``resp["retry-after"]`` (lowercased keys).
    """
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None) if resp is not None else None
    message = f"Gmail API error (status={status}): {exc}"

    if status in (401, 403):
        return GmailAuthError(message, status_code=status)
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        retry_after = None
        if resp is not None:
            try:
                retry_after = _parse_retry_after(resp.get("retry-after"))
            except Exception:  # noqa: BLE001 — header lookup must not raise
                retry_after = None
        return _RetryableGmailError(message, status_code=status, retry_after=retry_after)
    return GmailAPIError(message, status_code=status)


def _with_retry(fn):
    return retry(
        retry=retry_if_exception_type(_RetryableGmailError),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_retry_wait,
        reraise=True,
    )(fn)


# ── Client ────────────────────────────────────────────────────────


class GmailClient:
    """Async facade over ``googleapiclient.discovery.build("gmail", "v1")``.

    The Google service object is constructed lazily so tests can
    instantiate :class:`GmailClient` without triggering OAuth or HTTP
    setup. Every public method returns a coroutine that wraps the
    synchronous Google call in ``asyncio.to_thread`` and is protected
    by the tenacity retry decorator.
    """

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        *,
        user_id: str = "me",
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._user_id = user_id
        # Lazy — built on first method call.
        self._service = None

    def _get_service(self):
        """Return the underlying Gmail service, building it on demand."""
        if self._service is None:
            from googleapiclient.discovery import build

            # ``self._credentials_path`` was already resolved by the
            # factory (bundled-or-override) — pass it through as the
            # explicit secrets path so load_credentials skips its own
            # resolution step.
            creds = load_credentials(
                self._token_path,
                client_secrets_path=self._credentials_path or None,
            )
            # cache_discovery=False avoids a noisy "file_cache is unavailable
            # when using oauth2client >= 4.0.0" warning under app-default auth.
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    # ── Public async API ──────────────────────────────────────────

    async def get_profile(self) -> dict:
        """Fetch the authenticated user's profile (auth-probe endpoint).

        ``users.getProfile`` is the cheapest Gmail call that exercises the
        access token — used by :meth:`GmailHarvesterPlugin.test_connection`.
        """
        return await asyncio.to_thread(self._get_profile_sync)

    @_with_retry
    def _get_profile_sync(self) -> dict:
        service = self._get_service()
        try:
            return service.users().getProfile(userId=self._user_id).execute()
        except Exception as exc:  # googleapiclient.errors.HttpError + transport
            raise _classify_http_error(exc) from exc

    async def list_threads(
        self,
        query: str,
        *,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> dict:
        """Run a thread search via ``users.threads.list``.

        Uses Gmail's token-based pagination: pass ``page_token=None`` for
        the first page; the response carries ``nextPageToken`` until
        exhausted. An empty ``q`` matches every thread (subject to the
        account's storage state); the harvester always passes a built
        query so this case isn't expected.
        """
        return await asyncio.to_thread(
            self._list_threads_sync, query, page_token, max_results
        )

    @_with_retry
    def _list_threads_sync(
        self,
        query: str,
        page_token: str | None,
        max_results: int,
    ) -> dict:
        service = self._get_service()
        try:
            return (
                service.users()
                .threads()
                .list(
                    userId=self._user_id,
                    q=query,
                    pageToken=page_token,
                    maxResults=max_results,
                )
                .execute()
            )
        except Exception as exc:
            raise _classify_http_error(exc) from exc

    async def get_thread(self, thread_id: str, *, format: str = "full") -> dict:
        """Fetch a single thread by ID with full message payloads."""
        return await asyncio.to_thread(self._get_thread_sync, thread_id, format)

    @_with_retry
    def _get_thread_sync(self, thread_id: str, format: str) -> dict:
        service = self._get_service()
        try:
            return (
                service.users()
                .threads()
                .get(userId=self._user_id, id=thread_id, format=format)
                .execute()
            )
        except Exception as exc:
            raise _classify_http_error(exc) from exc

    async def list_labels(self) -> list[dict]:
        """List all labels on the authenticated mailbox.

        Used to map user-friendly label names (``"Inbox"``) to the system
        IDs Gmail uses internally — though for the search-query path the
        names are passed directly via ``label:Name``.
        """
        return await asyncio.to_thread(self._list_labels_sync)

    @_with_retry
    def _list_labels_sync(self) -> list[dict]:
        service = self._get_service()
        try:
            result = (
                service.users().labels().list(userId=self._user_id).execute()
            )
        except Exception as exc:
            raise _classify_http_error(exc) from exc
        return list(result.get("labels") or [])

    async def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download an attachment's raw bytes by message + attachment ID.

        Gmail returns attachments base64url-encoded; we decode here so
        the caller (and on-disk store) sees plain bytes.
        """
        return await asyncio.to_thread(
            self._get_attachment_sync, message_id, attachment_id
        )

    @_with_retry
    def _get_attachment_sync(self, message_id: str, attachment_id: str) -> bytes:
        import base64

        service = self._get_service()
        try:
            payload = (
                service.users()
                .messages()
                .attachments()
                .get(userId=self._user_id, messageId=message_id, id=attachment_id)
                .execute()
            )
        except Exception as exc:
            raise _classify_http_error(exc) from exc
        data = payload.get("data") or ""
        return base64.urlsafe_b64decode(data.encode("ascii")) if data else b""

    async def aclose(self) -> None:
        """Release any client-owned resources (best-effort).

        ``googleapiclient`` holds its own httplib2 Http instance that has
        no async-aware close; the underlying socket is freed when the
        service is garbage-collected. Provided for symmetry with
        :class:`JiraClient.aclose`.
        """
        self._service = None
