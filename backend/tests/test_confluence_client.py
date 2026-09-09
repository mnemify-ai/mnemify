"""Unit tests for :class:`ConfluenceClient` (ATL-10).

All tests mock ``atlassian.Confluence`` at its import site inside
``src.harvester.confluence.client`` so no network is required.  The
tests cover:

1. Lazy construction — ``Confluence(...)`` is NOT called by the
   ``ConfluenceClient`` constructor and is called exactly once across
   successive method invocations.
2. Happy-path for every public method.
3. 401 → :class:`ConfluenceAuthError`; 404 → generic
   :class:`ConfluenceAPIError`.
4. 429-then-success — retry harness honours ``Retry-After`` (we patch
   ``tenacity.nap.sleep`` to make the test instant).
5. 5xx-then-success — retry harness triggers on 500 too.
6. Pagination smoke — caller drives ``start`` and we return the raw
   envelope each time.
7. ``download_attachment_content`` uses the Atlassian client's
   authenticated session rather than issuing a new one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from src.harvester.confluence.client import (
    ConfluenceAPIError,
    ConfluenceAuthError,
    ConfluenceClient,
)


# ── Fixtures / helpers ───────────────────────────────────────────


def _http_error(status_code: int, retry_after: str | None = None) -> HTTPError:
    """Build an ``HTTPError`` whose attached response carries ``status_code``."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    return HTTPError(f"HTTP {status_code}", response=response)


@pytest.fixture
def confluence_cls():
    """Patch the ``Confluence`` symbol imported by ``client.py``."""
    with patch("src.harvester.confluence.client.Confluence") as cls:
        yield cls


@pytest.fixture(autouse=True)
def instant_client_sleep():
    """Make the client's retry-sleep callable instantaneous.

    ``ConfluenceClient.__init__`` binds ``self._sleep = asyncio.sleep``.
    We patch ``asyncio.sleep`` at the ``client`` import site so every
    client constructed during a test captures the no-op instead.
    """
    async def _noop(_seconds: float) -> None:
        return None

    with patch("src.harvester.confluence.client.asyncio.sleep", new=_noop):
        yield


# ── 1. Lazy construction ─────────────────────────────────────────


async def test_constructor_does_not_build_underlying_client(confluence_cls):
    """``__init__`` must NOT call ``atlassian.Confluence``."""
    ConfluenceClient(
        base_url="https://example.atlassian.net/wiki",
        email="bot@example.com",
        token="tok",
    )
    confluence_cls.assert_not_called()


async def test_first_method_call_constructs_client_once(confluence_cls):
    """First method call constructs the client; subsequent calls reuse it."""
    instance = confluence_cls.return_value
    instance.get_all_pages_from_space.return_value = {"results": [], "size": 0}
    instance.get_page_by_id.return_value = {"id": "1"}

    client = ConfluenceClient(
        base_url="https://example.atlassian.net/wiki",
        email="bot@example.com",
        token="tok",
    )

    assert confluence_cls.call_count == 0
    await client.list_pages_in_space("ENG")
    assert confluence_cls.call_count == 1

    await client.get_page("1")
    # Still 1 — the underlying client is cached.
    assert confluence_cls.call_count == 1

    # Construction kwargs match the Phase 1 decision (cloud=True,
    # basic-auth via username+password).
    confluence_cls.assert_called_once_with(
        url="https://example.atlassian.net/wiki",
        username="bot@example.com",
        password="tok",
        cloud=True,
    )


# ── 2. Happy-path per method ─────────────────────────────────────


async def test_list_pages_in_space_returns_envelope(confluence_cls):
    envelope = {
        "results": [{"id": "1"}, {"id": "2"}],
        "start": 0,
        "limit": 100,
        "size": 2,
        "_links": {"next": "/rest/api/..."},
    }
    confluence_cls.return_value.get_all_pages_from_space.return_value = envelope

    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.list_pages_in_space("ENG", expand=["version"], start=0, limit=100)

    assert result is envelope
    confluence_cls.return_value.get_all_pages_from_space.assert_called_once_with(
        space="ENG", start=0, limit=100, expand="version"
    )


async def test_list_pages_in_space_normalises_bare_list(confluence_cls):
    """``atlassian-python-api`` can return a bare list; client normalises."""
    confluence_cls.return_value.get_all_pages_from_space.return_value = [
        {"id": "1"},
        {"id": "2"},
    ]
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.list_pages_in_space("ENG", start=5, limit=50)
    assert result == {
        "results": [{"id": "1"}, {"id": "2"}],
        "start": 5,
        "limit": 50,
        "size": 2,
    }


async def test_get_page_applies_default_expand(confluence_cls):
    confluence_cls.return_value.get_page_by_id.return_value = {"id": "abc", "title": "t"}

    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.get_page("abc")

    assert result == {"id": "abc", "title": "t"}
    call_kwargs = confluence_cls.return_value.get_page_by_id.call_args.kwargs
    expand = call_kwargs["expand"]
    for required in (
        "body.storage",
        "ancestors",
        "version",
        "metadata.labels",
        "metadata.properties",
    ):
        assert required in expand


async def test_get_page_custom_expand_overrides_default(confluence_cls):
    confluence_cls.return_value.get_page_by_id.return_value = {}
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    await client.get_page("abc", expand=["version"])
    assert confluence_cls.return_value.get_page_by_id.call_args.kwargs["expand"] == "version"


async def test_list_attachments_returns_envelope(confluence_cls):
    envelope = {"results": [{"id": "att1"}], "size": 1}
    confluence_cls.return_value.get_attachments_from_content.return_value = envelope

    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.list_attachments("page-1")
    assert result is envelope
    confluence_cls.return_value.get_attachments_from_content.assert_called_once_with("page-1")


async def test_download_attachment_content_uses_session(confluence_cls):
    """Attachment download reuses the Atlassian client's authed session
    and follows the 302 to the signed media CDN."""
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.content = b"binary-payload"
    response.url = "https://api.media.atlassian.com/file/x/binary?token=y"
    session = MagicMock()
    session.get.return_value = response
    confluence_cls.return_value._session = session

    url = (
        "https://ex.atlassian.net/wiki/rest/api/content/"
        "1/child/attachment/att-1/download"
    )
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    data = await client.download_attachment_content(url)
    assert data == b"binary-payload"
    assert session.get.call_count == 1
    args, kwargs = session.get.call_args
    assert args == (url,)
    assert kwargs["allow_redirects"] is True
    assert kwargs["headers"]["Accept"] == "*/*"
    assert kwargs["headers"]["Authorization"].startswith("Basic ")


# ── 3. Non-retryable error mapping ───────────────────────────────


async def test_401_raises_auth_error(confluence_cls):
    confluence_cls.return_value.get_page_by_id.side_effect = _http_error(401)
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    with pytest.raises(ConfluenceAuthError) as excinfo:
        await client.get_page("abc")
    assert excinfo.value.status_code == 401
    # AuthError is a subclass of APIError — callers can catch either.
    assert isinstance(excinfo.value, ConfluenceAPIError)


async def test_403_raises_auth_error(confluence_cls):
    confluence_cls.return_value.get_page_by_id.side_effect = _http_error(403)
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    with pytest.raises(ConfluenceAuthError):
        await client.get_page("abc")


async def test_404_raises_generic_api_error_no_retry(confluence_cls):
    """404 is not retryable; it surfaces as ``ConfluenceAPIError`` immediately."""
    confluence_cls.return_value.get_page_by_id.side_effect = _http_error(404)
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    with pytest.raises(ConfluenceAPIError) as excinfo:
        await client.get_page("abc")
    # Not an auth error
    assert not isinstance(excinfo.value, ConfluenceAuthError)
    assert excinfo.value.status_code == 404
    # Called exactly once — no retry on non-retryable 4xx.
    assert confluence_cls.return_value.get_page_by_id.call_count == 1


# ── 4. Retry on 429 / 5xx ────────────────────────────────────────


async def test_429_then_success(confluence_cls):
    """429 triggers retry; second attempt succeeds."""
    confluence_cls.return_value.get_page_by_id.side_effect = [
        _http_error(429, retry_after="0"),
        {"id": "abc"},
    ]
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.get_page("abc")
    assert result == {"id": "abc"}
    assert confluence_cls.return_value.get_page_by_id.call_count == 2


async def test_500_then_success(confluence_cls):
    """5xx is retried identically to 429."""
    confluence_cls.return_value.get_page_by_id.side_effect = [
        _http_error(500),
        _http_error(503),
        {"id": "abc"},
    ]
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    result = await client.get_page("abc")
    assert result == {"id": "abc"}
    assert confluence_cls.return_value.get_page_by_id.call_count == 3


async def test_retry_exhaustion_raises_api_error(confluence_cls):
    """After max attempts, retryable failure surfaces as ``ConfluenceAPIError``."""
    confluence_cls.return_value.get_page_by_id.side_effect = _http_error(503)
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    with pytest.raises(ConfluenceAPIError) as excinfo:
        await client.get_page("abc")
    assert excinfo.value.status_code == 503
    assert not isinstance(excinfo.value, ConfluenceAuthError)
    # Retried up to the configured maximum
    assert confluence_cls.return_value.get_page_by_id.call_count >= 3


# ── 5. Pagination smoke ──────────────────────────────────────────


async def test_pagination_caller_loop(confluence_cls):
    """Caller loops on ``list_pages_in_space`` with advancing ``start``.

    The client itself does not paginate — it hands back each envelope
    unchanged and the caller (``PageExtractor`` in ATL-11) drives the
    loop.  This test pretends to be that caller.
    """
    confluence_cls.return_value.get_all_pages_from_space.side_effect = [
        {"results": [{"id": "1"}, {"id": "2"}], "start": 0, "limit": 2, "size": 2},
        {"results": [{"id": "3"}], "start": 2, "limit": 2, "size": 1},
        {"results": [], "start": 3, "limit": 2, "size": 0},
    ]

    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")

    collected: list[dict] = []
    start = 0
    limit = 2
    while True:
        envelope = await client.list_pages_in_space("ENG", start=start, limit=limit)
        batch = envelope["results"]
        if not batch:
            break
        collected.extend(batch)
        if len(batch) < limit:
            break
        start += len(batch)

    assert [p["id"] for p in collected] == ["1", "2", "3"]
    # Two REST calls — the first fills a full page (batch == limit, loop
    # continues), the second returns a short batch (``len(batch) < limit``)
    # so the caller exits without a third call.
    assert confluence_cls.return_value.get_all_pages_from_space.call_count == 2


# ── 6. aclose is a no-op ─────────────────────────────────────────


async def test_aclose_is_noop(confluence_cls):
    """``atlassian-python-api`` is sync; ``aclose`` has nothing to pump."""
    client = ConfluenceClient("https://ex.atlassian.net/wiki", "e", "t")
    # No error, returns None, does not construct the underlying client.
    assert await client.aclose() is None
    confluence_cls.assert_not_called()
