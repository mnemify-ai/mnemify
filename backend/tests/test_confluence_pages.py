"""Unit tests for :class:`PageExtractor` (ATL-11).

All tests mock :class:`ConfluenceClient` — no network, no Atlassian SDK
involvement.  Coverage targets per the ATL-11 acceptance criteria:

1. Multi-space enumeration flattens pages from each space.
2. ``since`` filter drops pages whose ``version.when`` is older.
3. Pagination loop — two API pages aggregated correctly; loop
   terminates when a short page is returned.
4. Empty space returns nothing, no error.
5. :meth:`get_full_page` passes the full expand list from plan §3.1.
6. :meth:`list_page_attachments` unwraps the envelope; empty / missing
   ``results`` yields an empty list.
7. :meth:`_extract_ancestor_chain` — parametrised over
   no-ancestors / 1 / 3 / malformed-missing-id cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.harvester.confluence.pages import PageExtractor


# ── Fixtures / helpers ───────────────────────────────────────────


def _page(
    page_id: str,
    *,
    title: str = "untitled",
    when: str | None = "2026-04-18T10:00:00.000Z",
    ancestors: list[dict] | None = None,
) -> dict:
    """Build a minimal page dict shaped like the Atlassian REST envelope."""
    out: dict[str, Any] = {
        "id": page_id,
        "title": title,
        "type": "page",
    }
    if when is not None:
        out["version"] = {"when": when, "number": 1}
    if ancestors is not None:
        out["ancestors"] = ancestors
    return out


def _envelope(results: list[dict], *, start: int = 0, limit: int = 100) -> dict:
    return {
        "results": results,
        "start": start,
        "limit": limit,
        "size": len(results),
    }


@pytest.fixture
def client() -> MagicMock:
    """A MagicMock ``ConfluenceClient`` with the async methods we use."""
    m = MagicMock()
    m.list_pages_in_space = AsyncMock()
    m.get_page = AsyncMock()
    m.list_attachments = AsyncMock()
    return m


async def _collect(agen) -> list[dict]:
    """Drain an async iterator into a list."""
    out: list[dict] = []
    async for item in agen:
        out.append(item)
    return out


# ── 1. Multi-space enumeration ───────────────────────────────────


async def test_list_pages_iterates_each_space(client):
    """Two spaces, one short page each → all pages yielded in order."""
    client.list_pages_in_space.side_effect = [
        _envelope([_page("1"), _page("2")]),  # ENG, short page → no next call
        _envelope([_page("3")]),              # PROD, short page → no next call
    ]
    extractor = PageExtractor(client)

    result = await _collect(extractor.list_pages(["ENG", "PROD"]))

    assert [p["id"] for p in result] == ["1", "2", "3"]
    assert client.list_pages_in_space.await_count == 2
    # First call asked for space ENG, second for PROD
    first_kwargs = client.list_pages_in_space.await_args_list[0].kwargs
    second_kwargs = client.list_pages_in_space.await_args_list[1].kwargs
    assert first_kwargs["space_key"] == "ENG"
    assert second_kwargs["space_key"] == "PROD"


async def test_list_pages_empty_space_keys_yields_nothing(client):
    """No spaces → no API calls, empty output."""
    extractor = PageExtractor(client)
    result = await _collect(extractor.list_pages([]))
    assert result == []
    client.list_pages_in_space.assert_not_awaited()


# ── 2. since is accepted but ignored (per-doc Layer 1 dedups upstream) ──


async def test_list_pages_ignores_since(client):
    """``since`` is accepted for compat but no longer filters.

    The previous client-side drop broke Manage Scope expansion (newly-added
    spaces' pages have old ``version.when`` and would be filtered out before
    the orchestrator's per-doc Layer 1 short-circuit could see them). The
    orchestrator now deduplicates per-doc; this method returns everything.
    """
    cutoff = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    client.list_pages_in_space.side_effect = [
        _envelope([
            _page("old", when="2026-04-17T09:00:00.000Z"),
            _page("new", when="2026-04-18T13:00:00.000Z"),
            _page("boundary", when="2026-04-18T12:00:00.000Z"),
        ]),
    ]
    extractor = PageExtractor(client)

    result = await _collect(extractor.list_pages(["ENG"], since=cutoff))

    assert sorted(p["id"] for p in result) == ["boundary", "new", "old"]


async def test_list_pages_no_since_yields_everything(client):
    """Without ``since``, every page comes through (including missing-when)."""
    client.list_pages_in_space.side_effect = [
        _envelope([
            _page("a", when=None),
            _page("b", when="2026-04-18T13:00:00.000Z"),
        ]),
    ]
    extractor = PageExtractor(client)

    result = await _collect(extractor.list_pages(["ENG"]))

    assert [p["id"] for p in result] == ["a", "b"]


async def test_list_pages_requests_version_expand(client):
    """``expand=version`` is still requested — downstream code reads
    ``version.when`` for DocRef.modified_at, which the per-doc Layer 1
    short-circuit needs."""
    client.list_pages_in_space.side_effect = [_envelope([])]
    extractor = PageExtractor(client)

    await _collect(extractor.list_pages(["ENG"], since=datetime.now(timezone.utc)))

    kwargs = client.list_pages_in_space.await_args_list[0].kwargs
    assert "version" in kwargs["expand"]


# ── 3. Pagination ────────────────────────────────────────────────


async def test_list_pages_paginates_two_api_pages(client):
    """Full page (size==limit) triggers a second call; short page terminates the loop."""
    page_size = PageExtractor._PAGE_SIZE
    first_batch = [_page(str(i)) for i in range(page_size)]
    second_batch = [_page("last")]

    client.list_pages_in_space.side_effect = [
        _envelope(first_batch, start=0, limit=page_size),
        _envelope(second_batch, start=page_size, limit=page_size),
    ]
    extractor = PageExtractor(client)

    result = await _collect(extractor.list_pages(["ENG"]))

    assert len(result) == page_size + 1
    assert client.list_pages_in_space.await_count == 2
    assert client.list_pages_in_space.await_args_list[0].kwargs["start"] == 0
    assert client.list_pages_in_space.await_args_list[1].kwargs["start"] == page_size


async def test_list_pages_empty_first_page_terminates_loop(client):
    """Empty envelope on first call → no further calls, no yield."""
    client.list_pages_in_space.side_effect = [_envelope([])]
    extractor = PageExtractor(client)

    result = await _collect(extractor.list_pages(["ENG"]))

    assert result == []
    assert client.list_pages_in_space.await_count == 1


# ── 4. get_full_page ─────────────────────────────────────────────


async def test_get_full_page_uses_full_expand_list(client):
    """``get_page`` is called with the plan §3.1 expand set."""
    client.get_page.return_value = {"id": "123", "title": "hello"}
    extractor = PageExtractor(client)

    got = await extractor.get_full_page("123")

    assert got == {"id": "123", "title": "hello"}
    client.get_page.assert_awaited_once()
    call_kwargs = client.get_page.await_args.kwargs
    expand_arg = call_kwargs["expand"]
    assert set(expand_arg) == {
        "body.storage",
        "ancestors",
        "version",
        "metadata.labels",
        "metadata.properties",
        "history",
    }


async def test_get_full_page_passes_page_id_positionally(client):
    """First positional arg to ``client.get_page`` is the page id."""
    client.get_page.return_value = {}
    extractor = PageExtractor(client)

    await extractor.get_full_page("xyz-1")

    args, _ = client.get_page.await_args
    assert args[0] == "xyz-1"


# ── 5. list_page_attachments ─────────────────────────────────────


async def test_list_page_attachments_unwraps_results(client):
    client.list_attachments.return_value = {
        "results": [{"id": "a1"}, {"id": "a2"}],
        "size": 2,
    }
    extractor = PageExtractor(client)

    result = await extractor.list_page_attachments("p1")

    assert result == [{"id": "a1"}, {"id": "a2"}]


async def test_list_page_attachments_no_results_key(client):
    """A malformed envelope without a ``results`` key returns an empty list."""
    client.list_attachments.return_value = {}
    extractor = PageExtractor(client)

    result = await extractor.list_page_attachments("p1")

    assert result == []


async def test_list_page_attachments_none_envelope(client):
    """Client returning ``None`` → empty list (defensive, not expected)."""
    client.list_attachments.return_value = None
    extractor = PageExtractor(client)

    result = await extractor.list_page_attachments("p1")

    assert result == []


# ── 6. _extract_ancestor_chain — parametrised ────────────────────


@pytest.mark.parametrize(
    "page, expected",
    [
        pytest.param({}, [], id="no-ancestors-key"),
        pytest.param({"ancestors": []}, [], id="empty-ancestors-list"),
        pytest.param(
            {"ancestors": [{"id": "root", "title": "Root"}]},
            [{"id": "root", "title": "Root"}],
            id="one-ancestor",
        ),
        pytest.param(
            {
                "ancestors": [
                    {"id": "root", "title": "Root"},
                    {"id": "mid", "title": "Middle"},
                    {"id": "leaf", "title": "Leaf"},
                ]
            },
            [
                {"id": "root", "title": "Root"},
                {"id": "mid", "title": "Middle"},
                {"id": "leaf", "title": "Leaf"},
            ],
            id="three-ancestors",
        ),
        pytest.param(
            {
                "ancestors": [
                    {"id": "root", "title": "Root"},
                    {"title": "orphan-no-id"},      # dropped
                    {"id": "leaf", "title": "Leaf"},
                ]
            },
            [
                {"id": "root", "title": "Root"},
                {"id": "leaf", "title": "Leaf"},
            ],
            id="malformed-missing-id-dropped",
        ),
        pytest.param(
            {"ancestors": [{"id": "no-title"}]},
            [{"id": "no-title", "title": ""}],
            id="missing-title-defaults-empty",
        ),
        pytest.param(
            {"ancestors": [None, "not-a-dict", {"id": "keep"}]},
            [{"id": "keep", "title": ""}],
            id="non-dict-entries-dropped",
        ),
        pytest.param(
            {"ancestors": None},
            [],
            id="explicit-null-ancestors",
        ),
    ],
)
def test_extract_ancestor_chain(page, expected):
    assert PageExtractor._extract_ancestor_chain(page) == expected
