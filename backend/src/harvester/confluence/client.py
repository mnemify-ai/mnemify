"""Low-level Confluence API client.

Thin async façade over ``atlassian.Confluence(cloud=True, ...)``.  The
underlying library is synchronous, so every public method here wraps the
sync call in ``asyncio.to_thread(...)`` — matching the Phase 1 design
decision from 2026-04-19.

Retries on 429 and 5xx responses use ``tenacity``'s ``AsyncRetrying``
with a custom wait callable that honours the ``Retry-After`` header
(falling back to ``wait_random_exponential`` when absent).  Non-retryable
statuses map to typed exceptions — 401/403 become
:class:`ConfluenceAuthError`, everything else in the 4xx family becomes
:class:`ConfluenceAPIError`.

Usage::

    client = ConfluenceClient(base_url=..., email=..., token=...)
    pages = await client.list_pages_in_space("ENG", expand=["version"])
    page  = await client.get_page(page_id, expand=["body.storage"])
    await client.aclose()  # no-op for sync library; present for symmetry
"""

from __future__ import annotations

import asyncio
import logging
from collections import abc
from itertools import islice
from typing import Awaitable, Callable, TypeVar

from atlassian import Confluence
from requests.exceptions import HTTPError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)


T = TypeVar("T")


# ── Retry tuning ──────────────────────────────────────────────────
#
# Atlassian Cloud returns 429 with a ``Retry-After`` header (seconds).
# We cap exponential backoff and the honoured ``Retry-After`` hint at
# 60 seconds so a badly-behaved upstream can't hang a harvest run
# indefinitely — the plan doc §5 risk register treats rate-limit
# blowups as a cost issue to surface, not a silent wait.
_MAX_ATTEMPTS = 5
_WAIT_MULTIPLIER = 1.0
_WAIT_MAX = 60.0
_DEFAULT_RETRY_AFTER = 2.0


# ── Library compatibility ─────────────────────────────────────────
#
# This client speaks the ``atlassian-python-api`` 4.x surface, which maps
# onto the Confluence Cloud **v1** REST API (``/wiki/rest/api/...``).
# 5.0 turned ``Confluence`` into a facade whose Cloud implementation is
# partly v2-backed: list calls return lazy generators instead of result
# envelopes, and the methods below were renamed.  Rather than fail deep
# in a call stack with an opaque ``AttributeError``, check up front and
# name the remedy.  ``pyproject.toml`` pins ``<5`` to match.
_SUPPORTED_LIBRARY_RANGE = ">=4.0,<5"
_REQUIRED_CLIENT_METHODS = (
    "get_all_spaces",
    "get_all_pages_from_space",
    "get_page_child_by_type",
    "get_page_by_id",
    "get_attachments_from_content",
)


# ── Typed errors ──────────────────────────────────────────────────


class ConfluenceAPIError(Exception):
    """Raised when the Confluence REST API returns a non-2xx response.

    ``status_code`` carries the HTTP status for non-auth errors; it is
    ``None`` when the failure was a non-HTTP transport error.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.__cause__ = cause


class ConfluenceAuthError(ConfluenceAPIError):
    """Raised on 401/403 responses from the Confluence API.

    Surfaced separately so the plugin can translate it into a
    :class:`HealthStatus` with a clear remediation message without
    catching unrelated API errors.
    """


# ── Internal helpers ──────────────────────────────────────────────


def _as_envelope(result: object, *, start: int, limit: int) -> dict:
    """Coerce a list-endpoint response into a ``{"results": [...]}`` envelope.

    ``atlassian-python-api`` is inconsistent about what its list calls
    return: a full envelope dict for some endpoints, a bare list of
    result dicts for others, and — since 5.0's Cloud rewrite — a lazy
    generator that paginates internally.  Callers here (``pages.py``)
    share one pagination contract built on the envelope, so normalise at
    this boundary.

    Iterators are consumed with ``islice(..., limit)`` rather than
    ``list()``: that preserves the caller's page window (so the
    ``start += len(results)`` loop still advances correctly) and keeps a
    ``limit=1`` auth probe from walking an entire site.  Anything that is
    neither a mapping nor iterable raises :class:`ConfluenceAPIError` —
    an actionable message beats an ``AttributeError`` three frames up.
    """
    if isinstance(result, dict):
        return result
    if result is None:
        # A 204/empty body reaches us as ``None``; the endpoint simply had
        # nothing to return, which is not an error.
        results: list = []
    elif isinstance(result, (list, tuple)):
        results = list(result)
    elif isinstance(result, abc.Iterable) and not isinstance(result, (str, bytes)):
        results = list(islice(result, limit))
    else:
        raise ConfluenceAPIError(
            "Unexpected Confluence list response of type "
            f"{type(result).__name__!r} — expected a results envelope. "
            f"Installed atlassian-python-api: {_library_version()} "
            f"(mnemify requires {_SUPPORTED_LIBRARY_RANGE})."
        )
    return {"results": results, "start": start, "limit": limit, "size": len(results)}


def _assert_library_compatible(client: object) -> None:
    """Fail fast when the installed library lacks the v1 methods we call.

    5.x's Cloud implementation renamed ``get_page_by_id`` →
    ``get_content`` and ``get_attachments_from_content`` →
    ``get_attachments``, so a harvest under it would die with an
    ``AttributeError`` from the facade's ``__getattr__`` delegation.
    """
    missing = [name for name in _REQUIRED_CLIENT_METHODS if not hasattr(client, name)]
    if not missing:
        return
    raise ConfluenceAPIError(
        "Incompatible atlassian-python-api "
        f"{_library_version()} — missing {', '.join(missing)}. "
        f"Mnemify's Confluence client needs {_SUPPORTED_LIBRARY_RANGE}; "
        "reinstall with: pip install 'atlassian-python-api<5'"
    )


def _library_version() -> str:
    """Return the installed ``atlassian-python-api`` version, best-effort."""
    try:
        from importlib.metadata import version

        return version("atlassian-python-api")
    except Exception:  # noqa: BLE001 — diagnostics only
        return "unknown"


def _status_code(exc: BaseException) -> int | None:
    """Return the HTTP status code attached to ``exc``, if any."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "status_code", None)


def _redact_url(url: str) -> str:
    """Strip query-string secrets from ``url`` before logging.

    Confluence attachment URLs sometimes carry signed `ot=…` tokens; we
    log only the path + host to avoid leaking those into our log file.
    """
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:  # noqa: BLE001
        return url[:60] + "…"


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Parse a ``Retry-After`` header into seconds, tolerating absence."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # HTTP-date form is permitted by RFC 7231 but Atlassian Cloud
        # emits seconds.  We take the conservative route and ignore
        # un-parseable values rather than hand-roll a date parser.
        logger.debug("Unparseable Retry-After header: %r", raw)
        return None


def _is_retryable(exc: BaseException) -> bool:
    """True when ``exc`` represents a transient Confluence failure."""
    if not isinstance(exc, HTTPError):
        return False
    status = _status_code(exc)
    if status is None:
        return False
    return status == 429 or 500 <= status < 600


def _retry_wait(retry_state: RetryCallState) -> float:
    """Return the delay before the next retry.

    Honours ``Retry-After`` when present; otherwise falls back to a
    bounded exponential with full jitter.  The returned value is
    ``max(retry_after, exponential)`` so a server that asks us to wait
    longer than our default schedule is respected, while a tiny
    ``Retry-After: 0`` doesn't undercut backoff entirely.
    """
    exp_wait = wait_random_exponential(multiplier=_WAIT_MULTIPLIER, max=_WAIT_MAX)(retry_state)
    outcome = retry_state.outcome
    if outcome is None or not outcome.failed:
        return exp_wait
    retry_after = _retry_after_seconds(outcome.exception())
    if retry_after is None:
        return exp_wait
    return min(_WAIT_MAX, max(exp_wait, retry_after))


# ── Client ────────────────────────────────────────────────────────


class ConfluenceClient:
    """Async façade over ``atlassian.Confluence`` (cloud).

    The underlying :mod:`atlassian-python-api` client is constructed
    lazily on first use — ``__init__`` only records credentials so that
    tests (and factory paths) can instantiate a client without needing
    the full Atlassian library to reach out to the network on import.

    Every public method wraps the synchronous library call in
    ``asyncio.to_thread``, layered under a tenacity retry that handles
    429/5xx and honours ``Retry-After``.
    """

    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base_url = base_url
        self._email = email
        self._token = token
        self._confluence: Confluence | None = None
        # Test seam: overridable async sleep used between retry attempts.
        # Production uses ``asyncio.sleep``; tests inject a no-op to keep
        # the 429/5xx retry exercises fast.
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    # ── Lazy construction ─────────────────────────────────────────

    def _get_client(self) -> Confluence:
        """Construct the underlying ``atlassian.Confluence`` on first use."""
        if self._confluence is None:
            client = Confluence(
                url=self.base_url,
                username=self._email,
                password=self._token,
                cloud=True,
            )
            _assert_library_compatible(client)
            self._confluence = client
        return self._confluence

    # ── Retry harness ─────────────────────────────────────────────

    async def _run(self, fn: Callable[[], T]) -> T:
        """Execute ``fn`` in a worker thread under the tenacity retry policy.

        Translates the exception taxonomy at the edge:

        - Retryable (``HTTPError`` with 429/5xx): retried up to
          ``_MAX_ATTEMPTS`` with ``Retry-After``-aware backoff.  On
          exhaustion surfaces as :class:`ConfluenceAPIError`.
        - 401/403: :class:`ConfluenceAuthError` (no retry).
        - Other 4xx: :class:`ConfluenceAPIError` (no retry).
        - Non-HTTP transport errors: re-raised unchanged so callers see
          the original network exception.
        """
        retryer = AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            wait=_retry_wait,
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            sleep=self._sleep,
            reraise=True,
        )
        try:
            async for attempt in retryer:
                with attempt:
                    return await asyncio.to_thread(fn)
        except HTTPError as exc:
            status = _status_code(exc)
            if status in (401, 403):
                raise ConfluenceAuthError(
                    f"Confluence auth failed ({status}): check CONFLUENCE_EMAIL / "
                    "CONFLUENCE_API_TOKEN env vars",
                    status_code=status,
                    cause=exc,
                ) from exc
            raise ConfluenceAPIError(
                f"Confluence API error ({status}): {exc}",
                status_code=status,
                cause=exc,
            ) from exc
        # ``AsyncRetrying`` with ``reraise=True`` always either returns
        # from inside the loop or re-raises; this is unreachable.
        raise ConfluenceAPIError("ConfluenceClient retry loop exited without result")

    # ── Public async API ──────────────────────────────────────────

    async def list_spaces(
        self,
        limit: int = 1,
    ) -> dict:
        """List Confluence spaces — the cheapest authenticated endpoint.

        Used primarily by :meth:`ConfluenceHarvesterPlugin.test_connection`
        to verify credentials with minimal server-side work.  The returned
        envelope mirrors :meth:`list_pages_in_space` — a dict with a
        ``"results"`` key (possibly empty).
        """

        def _call() -> dict:
            client = self._get_client()
            result = client.get_all_spaces(start=0, limit=limit)
            return _as_envelope(result, start=0, limit=limit)

        return await self._run(_call)

    async def list_pages_in_space(
        self,
        space_key: str,
        expand: list[str] | None = None,
        start: int = 0,
        limit: int = 100,
    ) -> dict:
        """List pages in ``space_key`` — caller drives pagination.

        Returns the raw ``atlassian-python-api`` response envelope
        (``{"results": [...], "start", "limit", "size", "_links": {...}}``).
        The caller inspects ``_links.next`` / ``start + size < total``
        to decide whether to re-invoke with an advanced ``start``.
        """
        expand_str = ",".join(expand) if expand else None

        def _call() -> dict:
            client = self._get_client()
            result = client.get_all_pages_from_space(
                space=space_key,
                start=start,
                limit=limit,
                expand=expand_str,
            )
            # ``atlassian-python-api`` occasionally returns a bare list
            # from this endpoint (library quirk); normalise so callers
            # can always treat the result as an envelope dict.
            return _as_envelope(result, start=start, limit=limit)

        return await self._run(_call)

    async def list_child_pages(
        self,
        page_id: str,
        expand: list[str] | None = None,
        start: int = 0,
        limit: int = 100,
    ) -> dict:
        """List the direct child pages of ``page_id`` — caller drives pagination.

        Wraps ``get_page_child_by_type(type="page")`` (the
        ``/content/{id}/child/page`` endpoint).  The library returns a bare
        list of result dicts for this call, so we normalise into the same
        ``{"results": [...]}`` envelope :meth:`list_pages_in_space` returns —
        callers can share pagination logic between the two.
        """
        expand_str = ",".join(expand) if expand else None

        def _call() -> dict:
            client = self._get_client()
            result = client.get_page_child_by_type(
                page_id,
                type="page",
                start=start,
                limit=limit,
                expand=expand_str,
            )
            return _as_envelope(result, start=start, limit=limit)

        return await self._run(_call)

    async def get_page(
        self,
        page_id: str,
        expand: list[str] | None = None,
    ) -> dict:
        """Fetch a single page by ID.

        Default ``expand`` (when ``None``) asks for everything the
        plugin needs to build a ``ConfluencePage`` without a second
        round-trip: body + ancestors + version + labels + properties.
        """
        if expand is None:
            expand = [
                "body.storage",
                "ancestors",
                "version",
                "metadata.labels",
                "metadata.properties",
            ]
        expand_str = ",".join(expand)

        def _call() -> dict:
            client = self._get_client()
            return client.get_page_by_id(page_id, expand=expand_str)

        return await self._run(_call)

    async def list_attachments(self, page_id: str) -> dict:
        """List attachments for ``page_id`` — raw response envelope."""

        def _call() -> dict:
            client = self._get_client()
            return client.get_attachments_from_content(page_id)

        return await self._run(_call)

    async def download_attachment_content(self, url: str) -> bytes:
        """Download an attachment by its absolute URL, authenticated.

        Sends the request directly with explicit basic-auth header and an
        ``Accept: */*`` (the lib's default ``Accept: application/json``
        confuses Atlassian's binary download endpoint and triggers a 401
        on some tenants). Logs the response body when auth fails so we
        can tell whether it's a credentials problem vs a permissions one.
        """
        import base64

        creds = f"{self._email}:{self._token}".encode("utf-8")
        auth_header = "Basic " + base64.b64encode(creds).decode("ascii")

        def _call() -> bytes:
            client = self._get_client()
            session = client._session  # type: ignore[attr-defined]
            response = session.get(
                url,
                headers={
                    "Authorization": auth_header,
                    "Accept": "*/*",
                    "X-Atlassian-Token": "no-check",
                },
                allow_redirects=True,
            )
            if response.status_code >= 400:
                # Log URL (incl. query string) and a short slice of the body
                # so we can diagnose 401s without re-running with extra
                # instrumentation. Body is usually a short JSON/HTML error
                # — cap at 300 chars.
                body = (response.text or "")[:300].replace("\n", " ")
                logger.warning(
                    "Confluence attachment GET failed: status=%s url=%s "
                    "redirected_to=%s body=%r (email_set=%s token_set=%s)",
                    response.status_code,
                    url[:200],
                    (response.url if response.url != url else "—"),
                    body,
                    bool(self._email),
                    bool(self._token),
                )
                response.raise_for_status()
            return response.content

        return await self._run(_call)

    async def aclose(self) -> None:
        """Release any client-owned resources.

        ``atlassian-python-api`` is synchronous and has no ``close``/``aclose``
        to pump, so this is a no-op.  The method exists for symmetry with
        other clients and so :meth:`ConfluenceHarvesterPlugin.aclose` has
        something to await.
        """
        return None
