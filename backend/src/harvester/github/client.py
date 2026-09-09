"""Low-level GitHub client — async ``httpx`` over REST + GraphQL.

Mirrors the Notion plugin's direct-``httpx`` style and the Jira plugin's
typed-error + tenacity-retry harness. No GitHub-specific third-party
library — keeps the dep footprint to the existing ``httpx``.

Rate-limit handling has two distinct cases:

1. **Primary** — ``X-RateLimit-Remaining: 0`` plus
   ``X-RateLimit-Reset`` (epoch seconds). Standard 5000/hour authenticated
   REST budget; ~5000 points/hour GraphQL budget.
2. **Secondary** — "abuse detection" 403 with ``Retry-After`` header.
   Triggered by burst patterns regardless of remaining primary budget.

Both are translated to :class:`GitHubRateLimitError` (retryable) with
the appropriate sleep duration. The retry decorator caps individual
sleeps at 60s so a misconfigured header can't hang a harvest.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── Typed errors ──────────────────────────────────────────────────


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubAuthError(GitHubAPIError):
    """Raised on 401, terminal 403 (non-rate-limit), and "Bad credentials" responses."""


class _RetryableGitHubError(GitHubAPIError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class GitHubRateLimitError(_RetryableGitHubError):
    """Subclass for primary or secondary rate-limit responses."""


# ── Retry helpers ─────────────────────────────────────────────────

_MAX_RETRY_AFTER_SECONDS = 60.0
_MAX_ATTEMPTS = 5


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, _RetryableGitHubError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


def _classify_response(response: httpx.Response, body: dict | None = None) -> GitHubAPIError:
    """Translate an HTTP response into our typed exception set.

    Distinguishes:
    - 401 → :class:`GitHubAuthError`
    - 403 + ``X-RateLimit-Remaining: 0`` → :class:`GitHubRateLimitError`
      (primary; sleep to ``X-RateLimit-Reset``)
    - 403 + body message contains "secondary rate limit" or
      "abuse detection" → :class:`GitHubRateLimitError` (secondary;
      sleep to ``Retry-After``)
    - 403 otherwise → :class:`GitHubAuthError`
    - 429 → :class:`GitHubRateLimitError` (sleep to ``Retry-After``)
    - 5xx → :class:`_RetryableGitHubError` (exponential backoff)
    - else → :class:`GitHubAPIError` (terminal)
    """
    status = response.status_code
    headers = response.headers
    msg_body = (body or {}).get("message", "") if isinstance(body, dict) else ""
    base_msg = f"GitHub API error (status={status}): {msg_body or response.text[:200]}"

    if status == 401:
        return GitHubAuthError(base_msg, status_code=status)
    if status == 403:
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = headers.get("X-RateLimit-Reset")
            try:
                wait = max(0.0, float(reset) - time.time()) if reset else None
            except (TypeError, ValueError):
                wait = None
            return GitHubRateLimitError(
                f"{base_msg} (primary rate limit; X-RateLimit-Remaining=0)",
                status_code=status,
                retry_after=wait,
            )
        if "secondary rate limit" in msg_body.lower() or "abuse detection" in msg_body.lower():
            return GitHubRateLimitError(
                f"{base_msg} (secondary rate limit / abuse detection)",
                status_code=status,
                retry_after=_parse_retry_after(headers.get("Retry-After")),
            )
        return GitHubAuthError(base_msg, status_code=status)
    if status == 429:
        return GitHubRateLimitError(
            base_msg,
            status_code=status,
            retry_after=_parse_retry_after(headers.get("Retry-After")),
        )
    if 500 <= status < 600:
        return _RetryableGitHubError(base_msg, status_code=status)
    return GitHubAPIError(base_msg, status_code=status)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _with_retry(fn):
    return retry(
        retry=retry_if_exception_type(_RetryableGitHubError),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_retry_wait,
        reraise=True,
    )(fn)


# ── Client ────────────────────────────────────────────────────────


class GitHubClient:
    """Async REST + GraphQL client backed by ``httpx``."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.github.com",
        graphql_endpoint: str = "https://api.github.com/graphql",
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._graphql = graphql_endpoint
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "Mnemify-Harvester/0.1",
                },
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── REST ──────────────────────────────────────────────────────

    @_with_retry
    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict | list:
        """Single GET request. Returns parsed JSON; raises typed error on non-2xx."""
        url = path if path.startswith("http") else f"{self._api_base}{path}"
        try:
            resp = await self._get_http().get(url, params=params)
        except httpx.HTTPError as exc:
            raise _RetryableGitHubError(f"network error fetching {url}: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise _classify_response(resp, body)
        return resp.json()

    @_with_retry
    async def get_with_link(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[list | dict, str | None]:
        """GET + return ``(json_body, next_url_or_None)`` from the ``Link`` header.

        Used by paginated REST endpoints (``/repos/{r}/issues`` etc.).
        Caller passes the returned next-URL back as ``path`` to walk
        pages without re-computing query params.
        """
        url = path if path.startswith("http") else f"{self._api_base}{path}"
        try:
            resp = await self._get_http().get(url, params=params)
        except httpx.HTTPError as exc:
            raise _RetryableGitHubError(f"network error fetching {url}: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise _classify_response(resp, body)
        next_url = self._parse_next_link(resp.headers.get("Link"))
        return resp.json(), next_url

    # ── GraphQL ───────────────────────────────────────────────────

    @_with_retry
    async def graphql(self, query: str, variables: dict[str, Any]) -> dict:
        """POST a GraphQL query. Surfaces ``errors[]`` as :class:`GitHubAPIError`."""
        try:
            resp = await self._get_http().post(
                self._graphql,
                json={"query": query, "variables": variables},
            )
        except httpx.HTTPError as exc:
            raise _RetryableGitHubError(f"network error on GraphQL: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            raise _classify_response(resp, body)
        payload = resp.json()
        if errors := payload.get("errors"):
            # GraphQL errors always come with HTTP 200; surface the first one.
            first = errors[0]
            msg = f"GraphQL error: {first.get('message', '?')}"
            # Auth-shaped GraphQL errors look like:
            # "Resource not accessible by personal access token" (missing scope)
            # → translate to GitHubAuthError so the plugin can hint at PAT scopes.
            if "not accessible" in (first.get("message") or "").lower():
                raise GitHubAuthError(msg)
            raise GitHubAPIError(msg)
        return payload.get("data", {}) or {}

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _parse_next_link(link_header: str | None) -> str | None:
        """Pull the ``rel="next"`` URL out of an RFC 5988 ``Link`` header."""
        if not link_header:
            return None
        # Format: '<https://api.github.com/...?page=2>; rel="next", <...>; rel="last"'
        for part in link_header.split(","):
            chunk = part.strip()
            if 'rel="next"' in chunk and chunk.startswith("<"):
                end = chunk.find(">")
                if end > 0:
                    return chunk[1:end]
        return None
