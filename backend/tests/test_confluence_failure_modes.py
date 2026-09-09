"""Failure-mode tests for the Confluence plugin + client (ATL-53).

Covers the error boundary that separates transport-level failures
(rate limits, auth, server errors) from semantic edge cases (malformed
body, missing ancestors, empty space).  Runs without network by
driving :class:`ConfluenceClient` through a patched
``atlassian.Confluence`` instance (so ``_get_client()`` returns a
``MagicMock``) and the plugin through a mocked :class:`PageExtractor`.

Coverage map:

Client boundary (via ``ConfluenceClient._run``):

  1. 401  → :class:`ConfluenceAuthError`, no retry.
  2. 403  → :class:`ConfluenceAuthError`, no retry.
  3. 404  → :class:`ConfluenceAPIError`, no retry.
  4. 429  → retry honouring ``Retry-After`` until success.
  5. 429  → retry exhaustion surfaces as :class:`ConfluenceAPIError`.
  6. 500  → retry exhaustion surfaces as :class:`ConfluenceAPIError`.

Plugin boundary (via :class:`ConfluenceHarvesterPlugin`):

  7. Malformed ``body.storage.value`` (truncated XHTML) — fetch +
     ``extract_plain_text`` do not raise.
  8. Missing ancestors (``[]``) → ``parent_id``/``parent_title`` are
     ``None`` and ``ancestors == []``.
  9. Empty space → ``list_documents`` returns an empty list with no
     error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from src.harvester import DocRef, RawDocument
from src.harvester.confluence import ConfluenceConfig, ConfluenceHarvesterPlugin
from src.harvester.confluence.client import (
    ConfluenceAPIError,
    ConfluenceAuthError,
    ConfluenceClient,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "confluence"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


# ── Request-error factory ────────────────────────────────────────


def _http_error(status: int, *, retry_after: str | None = None) -> HTTPError:
    """Build an :class:`HTTPError` whose ``response`` carries ``status``
    and an optional ``Retry-After`` header.

    :mod:`requests`-shaped errors expose ``.response.status_code`` and
    ``.response.headers``; the client's retry policy reads both.  We
    construct a lightweight ``MagicMock`` response rather than a real
    :class:`requests.Response` so the tests stay hermetic.
    """
    response = MagicMock()
    response.status_code = status
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    err = HTTPError(f"{status} HTTP error")
    err.response = response  # type: ignore[attr-defined]
    return err


# ── Client-level failure modes ───────────────────────────────────


def _build_client_with_fake_confluence(fake: MagicMock) -> ConfluenceClient:
    """Wire a :class:`ConfluenceClient` so ``_get_client()`` returns ``fake``.

    Constructs a real client (so the tenacity retry harness runs) but
    replaces the underlying ``atlassian.Confluence`` singleton with the
    mock.  Also swaps the retry sleep for a no-op coroutine — the 429
    tests otherwise stall for seconds on the honoured ``Retry-After``.
    """
    client = ConfluenceClient(base_url="https://x.atlassian.net/wiki", email="", token="")
    client._confluence = fake  # bypass lazy init
    client._sleep = AsyncMock(return_value=None)  # type: ignore[assignment]
    return client


async def test_client_401_raises_auth_error():
    fake = MagicMock()
    fake.get_all_spaces.side_effect = _http_error(401)
    client = _build_client_with_fake_confluence(fake)

    with pytest.raises(ConfluenceAuthError) as exc:
        await client.list_spaces()
    assert exc.value.status_code == 401
    # No retry on 401 — called exactly once
    assert fake.get_all_spaces.call_count == 1


async def test_client_403_raises_auth_error():
    fake = MagicMock()
    fake.get_all_spaces.side_effect = _http_error(403)
    client = _build_client_with_fake_confluence(fake)

    with pytest.raises(ConfluenceAuthError) as exc:
        await client.list_spaces()
    assert exc.value.status_code == 403
    assert fake.get_all_spaces.call_count == 1


async def test_client_404_raises_api_error_no_retry():
    fake = MagicMock()
    fake.get_page_by_id.side_effect = _http_error(404)
    client = _build_client_with_fake_confluence(fake)

    with pytest.raises(ConfluenceAPIError) as exc:
        await client.get_page("missing-id")
    assert exc.value.status_code == 404
    # 404 is terminal — no retry
    assert fake.get_page_by_id.call_count == 1


async def test_client_429_retries_and_succeeds():
    """Two 429s (with Retry-After) then a 200 → success after retries."""
    fake = MagicMock()
    fake.get_all_spaces.side_effect = [
        _http_error(429, retry_after="0"),
        _http_error(429, retry_after="0"),
        {"results": [{"key": "ENG"}], "size": 1},
    ]
    client = _build_client_with_fake_confluence(fake)

    envelope = await client.list_spaces()
    assert envelope["results"] == [{"key": "ENG"}]
    assert fake.get_all_spaces.call_count == 3
    # Sleep was awaited between attempts (retry harness)
    assert client._sleep.await_count >= 2  # type: ignore[union-attr]


async def test_client_429_exhausts_retries_raises_api_error():
    """Persistent 429s surface as :class:`ConfluenceAPIError` after
    ``_MAX_ATTEMPTS``."""
    fake = MagicMock()
    fake.get_all_spaces.side_effect = _http_error(429, retry_after="0")
    client = _build_client_with_fake_confluence(fake)

    with pytest.raises(ConfluenceAPIError) as exc:
        await client.list_spaces()
    assert exc.value.status_code == 429


async def test_client_500_exhausts_retries_raises_api_error():
    """5xx failures retry, then surface as :class:`ConfluenceAPIError`."""
    fake = MagicMock()
    fake.get_all_spaces.side_effect = _http_error(500)
    client = _build_client_with_fake_confluence(fake)

    with pytest.raises(ConfluenceAPIError) as exc:
        await client.list_spaces()
    assert exc.value.status_code == 500
    # Retried — called more than once
    assert fake.get_all_spaces.call_count > 1


# ── Plugin-level failure modes ───────────────────────────────────


def _cfg(**overrides) -> ConfluenceConfig:
    base = {
        "base_url": "https://example.atlassian.net/wiki",
        "space_keys": ["ENG"],
    }
    base.update(overrides)
    return ConfluenceConfig(**base)


async def _as_async_iter(items: Iterable[dict]):
    for item in items:
        yield item


@pytest.fixture
def mock_client():
    with patch("src.harvester.confluence.plugin.ConfluenceClient") as ctor:
        instance = MagicMock()
        instance.list_spaces = AsyncMock()
        instance.download_attachment_content = AsyncMock()
        instance.aclose = AsyncMock(return_value=None)
        ctor.return_value = instance
        yield instance


@pytest.fixture
def mock_extractor():
    with patch("src.harvester.confluence.plugin.PageExtractor") as ctor:
        instance = MagicMock()
        instance.list_pages = MagicMock()
        instance.get_full_page = AsyncMock()
        instance.list_page_attachments = AsyncMock()
        ctor.return_value = instance
        yield instance


async def test_fetch_document_malformed_body_does_not_raise(mock_client, mock_extractor):
    """Truncated / unclosed XHTML in ``body.storage.value`` must not crash.

    :meth:`fetch_document` stores bytes verbatim and must return without
    raising. The bs4-permissive flatten test that used to live here moved
    out with ``extract_plain_text``; ``normalize`` exercises the same code
    path under :mod:`tests.test_confluence_normalizer`.
    """
    page = _load_fixture("page_malformed_body.json")
    mock_extractor.get_full_page.return_value = page
    mock_extractor.list_page_attachments.return_value = []

    plugin = ConfluenceHarvesterPlugin(_cfg())
    raw = await plugin.fetch_document(DocRef("400", "hint", "confluence"))

    # Bytes are preserved exactly as the API delivered them
    assert isinstance(raw, RawDocument)
    assert raw.content == page["body"]["storage"]["value"].encode("utf-8")


async def test_fetch_document_missing_ancestors_yields_null_parent(
    mock_client, mock_extractor
):
    """A page with an empty ``ancestors`` array → parent fields are ``None``.

    Uses the ATL-50 XHTML-rich fixture which intentionally has
    ``ancestors: []`` — asserts the plugin treats that as "top-level
    page" without error.
    """
    page = _load_fixture("page_xhtml_rich.json")
    assert page["ancestors"] == []
    mock_extractor.get_full_page.return_value = page
    mock_extractor.list_page_attachments.return_value = []

    plugin = ConfluenceHarvesterPlugin(_cfg())
    raw = await plugin.fetch_document(DocRef("300", "hint", "confluence"))

    md = raw.metadata
    assert md["ancestors"] == []
    assert md["parent_id"] is None
    assert md["parent_title"] is None


async def test_list_documents_empty_space_returns_no_docs(mock_client, mock_extractor):
    """Empty-space fixture → list_documents yields no results without error."""
    envelope = _load_fixture("page_empty_space.json")
    assert envelope["results"] == []

    mock_extractor.list_pages.return_value = _as_async_iter(envelope["results"])
    plugin = ConfluenceHarvesterPlugin(_cfg())
    docs = await plugin.list_documents()
    assert docs == []
