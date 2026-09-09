"""Unit tests for :class:`src.harvester.jira.issues.IssueExtractor` (ATL-23).

The extractor is a thin adapter over :class:`JiraClient` so every test
mocks the client and asserts both the *shape* of what reaches the
client (JQL string, fields list, pagination args) and the *shape* of
what comes back (async-iterator semantics, termination conditions).
No network I/O.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.harvester.jira.issues import IssueExtractor, _LIST_FIELDS


# ── Helpers ──────────────────────────────────────────────────────


def _page(issues: list[dict], next_page_token: str | None = None) -> dict:
    """Build a canonical ``/rest/api/3/search/jql`` response fragment.

    Under the enhanced-JQL contract the response no longer carries
    ``total`` / ``startAt`` / ``maxResults`` — pagination is driven
    entirely by ``nextPageToken``.  A falsy/absent token signals the
    last page.
    """
    page: dict = {"issues": issues}
    if next_page_token is not None:
        page["nextPageToken"] = next_page_token
    return page


def _issue(key: str) -> dict:
    """Minimal issue shape — enough for the extractor's yield contract."""
    return {"key": key, "fields": {"summary": f"Issue {key}", "updated": "2026-04-19T13:45:00.000+0000"}}


async def _drain(aiter) -> list[dict]:
    """Consume an async iterator into a list for test assertions."""
    out = []
    async for item in aiter:
        out.append(item)
    return out


@pytest.fixture
def client():
    """Mock :class:`JiraClient` — only ``jql_search`` / ``get_issue`` are used."""
    mock = AsyncMock()
    return mock


# ── 1. JQL construction ──────────────────────────────────────────


async def test_list_issues_builds_multi_project_jql(client):
    """Multi-project input produces ``project in (...)`` JQL."""
    client.jql_search.return_value = _page([])

    extractor = IssueExtractor(client)
    await _drain(extractor.list_issues(["ABC", "DEF"]))

    client.jql_search.assert_called_once()
    jql = client.jql_search.call_args.args[0]
    assert jql == "project in (ABC, DEF) ORDER BY updated DESC"


async def test_list_issues_builds_since_filtered_jql(client):
    """``since`` renders the Atlassian-format ``updated >= ...`` clause."""
    client.jql_search.return_value = _page([])

    extractor = IssueExtractor(client)
    await _drain(
        extractor.list_issues(["ABC"], since=datetime(2026, 4, 19, 13, 45))
    )

    jql = client.jql_search.call_args.args[0]
    assert jql == (
        'project = ABC AND updated >= "2026-04-19 13:45" ORDER BY updated DESC'
    )


# ── 2. Field-list minimisation ───────────────────────────────────


async def test_list_issues_passes_concise_fields(client):
    """Only the list-time fields (per plan §3.2) are requested."""
    client.jql_search.return_value = _page([])

    extractor = IssueExtractor(client)
    await _drain(extractor.list_issues(["ABC"]))

    kwargs = client.jql_search.call_args.kwargs
    assert kwargs["fields"] == _LIST_FIELDS
    # Sanity: the concrete field names the plan §3.2 requires must be present.
    for field in ("summary", "status", "project", "updated", "issuetype"):
        assert field in kwargs["fields"]


# ── 3. Pagination ────────────────────────────────────────────────


async def test_list_issues_paginates_past_first_page(client):
    """A 150-issue result over 100-item pages produces two calls.

    Page 1 carries ``nextPageToken``; page 2 omits it → loop terminates.
    """
    first_page = _page(
        [_issue(f"ABC-{i}") for i in range(1, 101)],
        next_page_token="tok-page-2",
    )
    second_page = _page([_issue(f"ABC-{i}") for i in range(101, 151)])
    client.jql_search.side_effect = [first_page, second_page]

    extractor = IssueExtractor(client)
    results = await _drain(extractor.list_issues(["ABC"]))

    assert len(results) == 150
    assert client.jql_search.call_count == 2
    # First call: no token. Second call: token fed forward from page 1.
    assert client.jql_search.call_args_list[0].kwargs["next_page_token"] is None
    assert client.jql_search.call_args_list[1].kwargs["next_page_token"] == "tok-page-2"


async def test_list_issues_stops_when_next_page_token_absent(client):
    """Loop exits once the response omits ``nextPageToken`` — even on a full page."""
    full_page = _page([_issue(f"ABC-{i}") for i in range(1, 101)])  # no token
    client.jql_search.return_value = full_page

    extractor = IssueExtractor(client)
    results = await _drain(extractor.list_issues(["ABC"]))

    assert len(results) == 100
    assert client.jql_search.call_count == 1


async def test_list_issues_respects_custom_page_size(client):
    """``page_size`` is forwarded to the client as ``max_results``."""
    client.jql_search.return_value = _page([_issue("ABC-1")])

    extractor = IssueExtractor(client)
    await _drain(extractor.list_issues(["ABC"], page_size=25))

    kwargs = client.jql_search.call_args.kwargs
    assert kwargs["max_results"] == 25


# ── 4. Defensive termination ─────────────────────────────────────


async def test_list_issues_empty_result_yields_nothing(client):
    """Empty project surfaces as an empty iterator with no error."""
    client.jql_search.return_value = {"issues": []}

    extractor = IssueExtractor(client)
    results = await _drain(extractor.list_issues(["ABC"]))

    assert results == []
    assert client.jql_search.call_count == 1


async def test_list_issues_breaks_on_unexpected_empty_page(client):
    """Mid-walk empty response terminates even when token keeps advancing.

    Defence against a degenerate server response where ``nextPageToken``
    is present but ``issues`` is empty — the extractor must not spin.
    """
    first_page = _page([_issue("ABC-1")], next_page_token="tok-page-2")
    empty_page = _page([], next_page_token="tok-would-loop-forever")
    client.jql_search.side_effect = [first_page, empty_page]

    extractor = IssueExtractor(client)
    results = await _drain(extractor.list_issues(["ABC"]))

    # Stops after the empty page — does not chase the runaway token.
    assert [r["key"] for r in results] == ["ABC-1"]
    assert client.jql_search.call_count == 2


async def test_list_issues_missing_token_terminates_loop(client):
    """If a mid-walk page omits ``nextPageToken`` the loop terminates cleanly."""
    first_page = _page(
        [_issue("ABC-1")], next_page_token="tok-page-2"
    )
    last_page = {"issues": [_issue("ABC-2")]}  # no nextPageToken key at all
    client.jql_search.side_effect = [first_page, last_page]

    extractor = IssueExtractor(client)
    results = await _drain(extractor.list_issues(["ABC"]))

    assert [r["key"] for r in results] == ["ABC-1", "ABC-2"]
    assert client.jql_search.call_count == 2


# ── 5. get_full_issue ────────────────────────────────────────────


async def test_get_full_issue_passes_all_fields_and_rendered_expand(client):
    """``get_full_issue`` requests the full field set and rendered HTML expansion."""
    expected = {"key": "ABC-1", "fields": {"summary": "hi"}}
    client.get_issue.return_value = expected

    extractor = IssueExtractor(client)
    result = await extractor.get_full_issue("ABC-1")

    assert result is expected
    client.get_issue.assert_called_once_with(
        "ABC-1",
        fields=["*all"],
        expand=["renderedFields"],
    )


async def test_get_full_issue_returns_raw_dict(client):
    """Return value is the raw REST dict — no flattening, no re-shaping."""
    raw = {
        "key": "ABC-1",
        "fields": {
            "summary": "S",
            "description": {"type": "doc", "version": 1, "content": []},
            "attachment": [{"id": "10001", "content": "https://example/att"}],
        },
    }
    client.get_issue.return_value = raw

    extractor = IssueExtractor(client)
    result = await extractor.get_full_issue("ABC-1")

    # Attachments preserved for ATL-31 consumption.
    assert result["fields"]["attachment"][0]["id"] == "10001"
    # ADF body preserved byte-for-byte.
    assert result["fields"]["description"]["type"] == "doc"


# ── 6. Round-trip: ``since`` round-trips from caller to JQL ──────


async def test_since_roundtrips_through_list_issues(client):
    """A caller-supplied ``since`` appears in the JQL verbatim (post-normalisation)."""
    client.jql_search.return_value = _page([])
    since = datetime(2026, 1, 2, 3, 4, 5)  # seconds should be stripped

    extractor = IssueExtractor(client)
    await _drain(extractor.list_issues(["ABC", "DEF"], since=since))

    jql = client.jql_search.call_args.args[0]
    assert jql == (
        'project in (ABC, DEF) AND updated >= "2026-01-02 03:04" ORDER BY updated DESC'
    )
