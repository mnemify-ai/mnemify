"""Low-level Jira API client (ATL-20).

Thin async facade over ``atlassian.Jira(cloud=True, ...)``.  The
underlying library is synchronous, so every public method here wraps
the sync call in ``asyncio.to_thread(...)`` — matching the Phase 1
design decision from 2026-04-19.

Responsibilities implemented in ATL-20:

- Lazy construction of the underlying ``atlassian.Jira`` client on first
  method call (tests can instantiate :class:`JiraClient` without the
  ``atlassian.Jira`` constructor firing).
- Tenacity retry decorator on 429 and 5xx responses, honouring the
  ``Retry-After`` response header when present.
- Typed exceptions:
    * :class:`JiraAPIError` — generic non-2xx wrapper.
    * :class:`JiraAuthError` (subclass) — 401 / 403 only.
    * :class:`_RetryableJiraError` (subclass, internal) — marks 429 / 5xx
      so tenacity can discriminate retryable from terminal failures.
      Because it is a subclass of :class:`JiraAPIError`, any leftover
      retryable error that escapes a retry budget still surfaces to the
      caller as a :class:`JiraAPIError`.

Usage::

    client = JiraClient(base_url=..., email=..., token=...)
    page   = await client.jql_search(
        "project = CONN ORDER BY updated DESC",
        fields=["summary", "status", "updated"],
        next_page_token=None,      # None = first page; feed response's
                                   # ``nextPageToken`` back for subsequent pages
        max_results=100,
    )
    issue  = await client.get_issue("CONN-123", expand=["renderedFields"])
    fields = await client.list_fields()
    blob   = await client.download_attachment(att_url)
    await client.aclose()  # no-op for sync library; present for symmetry
"""

from __future__ import annotations

import asyncio
import logging

import requests
from atlassian import Jira
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── Typed errors ──────────────────────────────────────────────────


class JiraAPIError(Exception):
    """Raised when the Jira REST API returns a non-2xx response.

    Instances carry the HTTP ``status_code`` (when known) so callers can
    discriminate, e.g. 404-as-missing vs a hard failure.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JiraAuthError(JiraAPIError):
    """Raised on 401/403 responses from the Jira API.

    Surfaced separately so the plugin can translate it into a
    :class:`HealthStatus` with a clear remediation message without
    catching unrelated API errors.
    """


class _RetryableJiraError(JiraAPIError):
    """Internal: marks a 429 or 5xx response as tenacity-retryable.

    Carries an optional ``retry_after`` (seconds) lifted from the
    ``Retry-After`` response header so the custom tenacity ``wait``
    callable can honour the server's back-off hint.  Subclasses
    :class:`JiraAPIError` so that a retry-exhausted failure still
    surfaces to callers as a :class:`JiraAPIError`.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


# ── Retry helpers ─────────────────────────────────────────────────

# Hard cap on Retry-After so a misconfigured header can't hang a harvest.
_MAX_RETRY_AFTER_SECONDS = 60.0
_MAX_ATTEMPTS = 5


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value as seconds (numeric only).

    HTTP-date form is allowed by the RFC but is rare from Atlassian
    Cloud; for Phase 1 we only honour the integer-seconds form and
    fall back to exponential back-off otherwise.
    """
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value))
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Tenacity ``wait`` callable: honour ``Retry-After`` when present."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, _RetryableJiraError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    # Fall back to capped exponential (1s, 2s, 4s, 8s, …, capped at 30s).
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _classify_response(exc: requests.HTTPError) -> JiraAPIError:
    """Translate a ``requests.HTTPError`` into our typed exception set.

    - 401 / 403 → :class:`JiraAuthError` (terminal).
    - 429 or 500-599 → :class:`_RetryableJiraError` (retryable).
    - else → :class:`JiraAPIError` (terminal).
    """
    response = exc.response
    status = response.status_code if response is not None else None
    message = f"Jira API error (status={status}): {exc}"

    if status in (401, 403):
        return JiraAuthError(message, status_code=status)
    if status == 429 or (status is not None and 500 <= status < 600):
        retry_after = _parse_retry_after(
            response.headers.get("Retry-After") if response is not None else None
        )
        return _RetryableJiraError(message, status_code=status, retry_after=retry_after)
    return JiraAPIError(message, status_code=status)


def _with_retry(fn):
    """Decorator applying the Jira retry policy to a sync callable.

    Retries only :class:`_RetryableJiraError`.  :class:`JiraAuthError`
    and the generic :class:`JiraAPIError` are terminal.  Re-raises the
    final exception (``reraise=True``) so the caller sees the real
    error, not a ``RetryError`` wrapper.
    """
    return retry(
        retry=retry_if_exception_type(_RetryableJiraError),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_retry_wait,
        reraise=True,
    )(fn)


# ── Client ────────────────────────────────────────────────────────


class JiraClient:
    """Async facade over ``atlassian.Jira`` (cloud).

    The underlying :mod:`atlassian-python-api` client is constructed
    lazily on first method call.  Every public method returns a
    coroutine that wraps the synchronous call in ``asyncio.to_thread``
    and is protected by a tenacity retry decorator.
    """

    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base_url = base_url
        self._email = email
        self._token = token
        # Lazy — constructed on first method call, so tests (and code
        # paths that never make a network call) don't trigger the
        # atlassian.Jira constructor.
        self._jira: Jira | None = None

    def _get_jira(self) -> Jira:
        """Return the underlying sync client, constructing it on demand."""
        if self._jira is None:
            self._jira = Jira(
                url=self.base_url,
                username=self._email,
                password=self._token,
                cloud=True,
            )
        return self._jira

    # ── Public async API ──────────────────────────────────────────

    async def jql_search(
        self,
        jql: str,
        fields: list[str] | None = None,
        next_page_token: str | None = None,
        max_results: int = 100,
        expand: list[str] | None = None,
    ) -> dict:
        """Run a JQL search via the new Cloud endpoint ``/rest/api/3/search/jql``.

        Uses token-based pagination: pass ``next_page_token=None`` for
        the first page, then feed the ``nextPageToken`` from the previous
        response back in to fetch the next page.  The response has no
        ``total`` field — iterate until ``nextPageToken`` is absent.

        An empty project surfaces as ``{"issues": []}`` rather than an
        error.
        """
        return await asyncio.to_thread(
            self._jql_search_sync,
            jql,
            fields,
            next_page_token,
            max_results,
            expand,
        )

    @_with_retry
    def _jql_search_sync(
        self,
        jql: str,
        fields: list[str] | None,
        next_page_token: str | None,
        max_results: int,
        expand: list[str] | None,
    ) -> dict:
        jira = self._get_jira()
        # atlassian.Jira.enhanced_jql accepts comma-separated strings for
        # fields/expand; normalise at the boundary.
        fields_arg: str | list[str] = ",".join(fields) if fields else "*all"
        expand_arg: str | None = ",".join(expand) if expand else None
        try:
            result = jira.enhanced_jql(
                jql,
                fields=fields_arg,
                nextPageToken=next_page_token,
                limit=max_results,
                expand=expand_arg,
            )
        except requests.HTTPError as exc:
            raise _classify_response(exc) from exc
        # Defensive: library signature is Optional[dict]; normalise to
        # the empty-project shape so callers never see ``None``.
        if result is None:
            return {"issues": []}
        return result

    async def get_issue(
        self,
        key: str,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> dict:
        """Fetch a single issue by key."""
        return await asyncio.to_thread(self._get_issue_sync, key, fields, expand)

    @_with_retry
    def _get_issue_sync(
        self,
        key: str,
        fields: list[str] | None,
        expand: list[str] | None,
    ) -> dict:
        jira = self._get_jira()
        fields_arg: str | list[str] = ",".join(fields) if fields else "*all"
        expand_arg: str | None = ",".join(expand) if expand else None
        try:
            result = jira.issue(key, fields=fields_arg, expand=expand_arg)
        except requests.HTTPError as exc:
            raise _classify_response(exc) from exc
        if result is None:
            raise JiraAPIError(f"Issue {key!r} not found", status_code=404)
        return result

    async def list_fields(self) -> list[dict]:
        """List all Jira fields (standard + custom).

        Used by :func:`src.harvester.jira.fields.discover_story_points_field`
        (ATL-40) to locate the site-specific Story Points custom field id.
        """
        return await asyncio.to_thread(self._list_fields_sync)

    @_with_retry
    def _list_fields_sync(self) -> list[dict]:
        jira = self._get_jira()
        try:
            result = jira.get_all_fields()
        except requests.HTTPError as exc:
            raise _classify_response(exc) from exc
        return list(result) if result else []

    async def get_myself(self) -> dict:
        """Fetch the authenticated user's profile via ``/rest/api/3/myself``.

        Used by :meth:`JiraHarvesterPlugin.test_connection` (ATL-24) as the
        canonical cheap auth-probe endpoint.  Returns the raw response dict
        (``accountId``, ``displayName``, ``emailAddress``, ...).
        """
        return await asyncio.to_thread(self._get_myself_sync)

    @_with_retry
    def _get_myself_sync(self) -> dict:
        jira = self._get_jira()
        try:
            result = jira.myself()
        except requests.HTTPError as exc:
            raise _classify_response(exc) from exc
        if result is None:
            raise JiraAPIError("Jira /rest/api/3/myself returned no body")
        return result

    async def download_attachment(self, url: str) -> bytes:
        """Download an attachment by its absolute content URL.

        Reuses the authenticated ``requests.Session`` that
        ``atlassian-python-api`` sets up — basic auth (email + token)
        is already configured on ``self._jira._session``.
        """
        return await asyncio.to_thread(self._download_attachment_sync, url)

    @_with_retry
    def _download_attachment_sync(self, url: str) -> bytes:
        jira = self._get_jira()
        try:
            response = jira._session.get(url)
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise _classify_response(exc) from exc
        return response.content

    async def aclose(self) -> None:
        """Release any client-owned resources.

        ``atlassian-python-api`` is synchronous and has no async close
        to pump.  Close the underlying ``requests.Session`` if we ever
        constructed it; keep it best-effort so teardown never raises.
        """
        if self._jira is not None:
            try:
                self._jira.close()
            except Exception:  # noqa: BLE001 — teardown must not raise
                logger.debug("JiraClient.aclose: underlying session close failed", exc_info=True)
        return None
