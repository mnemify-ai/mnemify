"""Low-level Notion API client.

Handles authentication, rate limiting, retries, and raw HTTP calls.
All other Notion modules (pages, databases, attachments) use this client
rather than making HTTP calls directly.

Usage:
    async with NotionClient(token="ntn_...") as client:
        response = await client.get("/pages/abc123")
        results = await client.post("/search", json={...})
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Notion API constants
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"

# Rate limiting: Notion allows 3 req/sec.
# We use 85% of capacity by default (rate_buffer=0.15). The previous
# 50% buffer halved throughput on big workspaces — 429s do happen but
# are retried with Retry-After honored, so leaving more headroom on
# the table than necessary just makes harvests slow.
DEFAULT_RATE_LIMIT = 3.0  # requests per second
DEFAULT_RATE_BUFFER = 0.15
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds


class NotionAPIError(Exception):
    """Raised when the Notion API returns an error response."""

    def __init__(self, status_code: int, code: str, message: str):
        """Initialize a structured Notion API error."""
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Notion API {status_code} ({code}): {message}")


class NotionRateLimitError(NotionAPIError):
    """Raised on 429 Too Many Requests. Contains retry_after hint."""

    def __init__(self, retry_after: float, message: str = "Rate limited"):
        """Initialize a rate limit error with a retry delay."""
        self.retry_after = retry_after
        super().__init__(429, "rate_limited", message)


class NotionClient:
    """Async Notion API client with rate limiting and retries.

    Use as an async context manager:
        async with NotionClient(token="...") as client:
            data = await client.get("/users/me")
    """

    def __init__(
        self,
        token: str,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        rate_buffer: float = DEFAULT_RATE_BUFFER,
        timeout: float = 30.0,
    ):
        """Initialize the Notion client and its HTTP transport.

        Rate limiting uses a sliding 1-second window. ``rate_capacity`` is
        derived from ``rate_limit * (1 - rate_buffer)`` and rounded to the
        nearest integer (floor 1). With the defaults (3.0 × 0.5 = 1.5 → 2),
        up to 2 requests may be in-flight within any 1-second window, so
        concurrent fetches actually interleave instead of serializing on a
        global lock.
        """
        self.token = token
        self._effective_rate = max(0.0, rate_limit * (1 - rate_buffer))
        self._rate_capacity = max(1, round(self._effective_rate))
        self._rate_window: deque[float] = deque()
        self._rate_lock = asyncio.Lock()

        self._http = httpx.AsyncClient(
            base_url=NOTION_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> NotionClient:
        """Return the client when entering an async context."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close the client when leaving an async context."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ── Rate limiting ──────────────────────────────────────────────

    async def _wait_for_rate_limit(self) -> None:
        """Admit a request under the sliding 1-second window.

        Concurrent callers may all pass immediately as long as fewer than
        ``_rate_capacity`` requests have started within the last 1 second.
        Otherwise the caller sleeps only until the oldest in-window request
        ages out — and then rechecks. The lock is only held around window
        mutation, never across ``asyncio.sleep``, so other tasks can make
        progress while one task is throttled.
        """
        loop = asyncio.get_event_loop()
        while True:
            async with self._rate_lock:
                now = loop.time()
                while self._rate_window and now - self._rate_window[0] >= 1.0:
                    self._rate_window.popleft()
                if len(self._rate_window) < self._rate_capacity:
                    self._rate_window.append(now)
                    return
                wait_time = 1.0 - (now - self._rate_window[0])
            if wait_time > 0:
                logger.debug(f"Rate limit: sleeping {wait_time:.3f}s (window full)")
                await asyncio.sleep(wait_time)

    # ── Core request method ────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> dict:
        """Send a Notion API request with retry and rate-limit handling."""
        for attempt in range(retries + 1):
            await self._wait_for_rate_limit()

            try:
                response = await self._http.request(method, path, **kwargs)
            except httpx.RequestError as e:
                if attempt < retries:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(f"Request error (attempt {attempt + 1}): {e}. Retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise

            # Success
            if response.status_code == 200:
                return response.json()

            # Rate limited — respect Retry-After
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", RETRY_BASE_DELAY * (2**attempt)))
                if attempt < retries:
                    logger.warning(f"Rate limited. Retrying in {retry_after}s (attempt {attempt + 1})")
                    await asyncio.sleep(retry_after)
                    continue
                raise NotionRateLimitError(retry_after)

            # Server errors — retry
            if response.status_code >= 500 and attempt < retries:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(f"Server error {response.status_code}. Retrying in {delay}s")
                await asyncio.sleep(delay)
                continue

            # Client error — don't retry
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise NotionAPIError(
                status_code=response.status_code,
                code=body.get("code", "unknown"),
                message=body.get("message", response.text[:200]),
            )

        # Should not reach here, but just in case
        raise NotionAPIError(0, "max_retries", f"Failed after {retries + 1} attempts")

    # ── Public HTTP methods ────────────────────────────────────────

    async def get(self, path: str, **kwargs: Any) -> dict:
        """Send a GET request to the Notion API."""
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict:
        """Send a POST request to the Notion API."""
        return await self._request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> dict:
        """Send a PATCH request to the Notion API."""
        return await self._request("PATCH", path, **kwargs)

    # ── Pagination helper ──────────────────────────────────────────

    async def paginate(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """Collect every result page from a cursor-paginated Notion endpoint."""
        all_results = []
        has_more = True
        next_cursor = None

        while has_more:
            request_body = {**(body or {}), "page_size": page_size}
            if next_cursor:
                request_body["start_cursor"] = next_cursor

            if method.upper() == "GET":
                data = await self.get(path, params=request_body)
            else:
                data = await self.post(path, json=request_body)

            results = data.get("results", [])
            all_results.extend(results)

            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")

            logger.debug(f"Paginate {path}: got {len(results)} results (total: {len(all_results)})")

        return all_results

    # ── Connection test ────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Fetch the current bot user to verify connectivity and auth."""
        return await self.get("/users/me")
