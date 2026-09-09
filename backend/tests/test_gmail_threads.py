"""Unit tests for :class:`src.harvester.gmail.threads.ThreadExtractor`.

The extractor is a thin async iterator over :class:`GmailClient`. The
client is mocked so these tests focus on extractor semantics: pagination
termination, the safety cap, defensive empty-page handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.harvester.gmail.client import GmailClient
from src.harvester.gmail.threads import ThreadExtractor


def _page(threads: list[dict], *, next_page_token: str | None = None) -> dict:
    page: dict = {"threads": threads}
    if next_page_token is not None:
        page["nextPageToken"] = next_page_token
    return page


def _stub(thread_id: str, snippet: str = "") -> dict:
    return {"id": thread_id, "snippet": snippet, "historyId": "h1"}


async def _collect(iterator) -> list[dict]:
    out: list[dict] = []
    async for item in iterator:
        out.append(item)
    return out


# ── Pagination ──────────────────────────────────────────────────


async def test_yields_threads_from_single_page():
    client = AsyncMock(spec=GmailClient)
    client.list_threads.return_value = _page([_stub("t1"), _stub("t2")])
    ext = ThreadExtractor(client)

    out = await _collect(ext.list_threads(query="q"))

    assert [t["id"] for t in out] == ["t1", "t2"]
    client.list_threads.assert_awaited_once()


async def test_pagination_terminates_on_absent_next_page_token():
    client = AsyncMock(spec=GmailClient)
    client.list_threads.side_effect = [
        _page([_stub("t1")], next_page_token="page2"),
        _page([_stub("t2")]),  # no nextPageToken → stop
    ]
    ext = ThreadExtractor(client)

    out = await _collect(ext.list_threads(query="q"))

    assert [t["id"] for t in out] == ["t1", "t2"]
    assert client.list_threads.await_count == 2


async def test_pagination_terminates_on_empty_threads_defensive():
    """A degenerate page with empty threads + non-None token must not loop forever."""
    client = AsyncMock(spec=GmailClient)
    client.list_threads.side_effect = [
        _page([_stub("t1")], next_page_token="page2"),
        _page([], next_page_token="still-not-none"),  # empty → defensive break
    ]
    ext = ThreadExtractor(client)

    out = await _collect(ext.list_threads(query="q"))

    assert [t["id"] for t in out] == ["t1"]


# ── max_threads cap ─────────────────────────────────────────────


async def test_max_threads_cap_stops_mid_page():
    client = AsyncMock(spec=GmailClient)
    client.list_threads.return_value = _page(
        [_stub("t1"), _stub("t2"), _stub("t3"), _stub("t4")],
        next_page_token="more",
    )
    ext = ThreadExtractor(client)

    out = await _collect(ext.list_threads(query="q", max_threads=2))

    assert [t["id"] for t in out] == ["t1", "t2"]


async def test_max_threads_none_runs_unbounded_until_pages_exhausted():
    client = AsyncMock(spec=GmailClient)
    client.list_threads.side_effect = [
        _page([_stub("t1")], next_page_token="p2"),
        _page([_stub("t2")]),
    ]
    ext = ThreadExtractor(client)

    out = await _collect(ext.list_threads(query="q", max_threads=None))

    assert len(out) == 2


# ── get_full_thread ─────────────────────────────────────────────


async def test_get_full_thread_passes_format_full():
    client = AsyncMock(spec=GmailClient)
    client.get_thread.return_value = {"id": "t1", "messages": []}
    ext = ThreadExtractor(client)

    result = await ext.get_full_thread("t1")

    assert result["id"] == "t1"
    client.get_thread.assert_awaited_once_with("t1", format="full")
