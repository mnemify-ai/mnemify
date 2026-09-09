"""Tests for src.harvester.github.repos.RepoExtractor pagination + since-cutoff."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.harvester.github.client import GitHubClient
from src.harvester.github.repos import RepoExtractor


@pytest.fixture
def mock_client():
    return AsyncMock(spec=GitHubClient)


async def test_list_issues_and_prs_follows_link_pagination(mock_client):
    # First page: 2 items + a next link; second page: 1 item + no next.
    mock_client.get_with_link.side_effect = [
        ([{"number": 1, "updated_at": "2026-05-13T14:00:00Z"},
          {"number": 2, "updated_at": "2026-05-12T14:00:00Z"}],
         "https://api.github.com/repos/o/r/issues?page=2"),
        ([{"number": 3, "updated_at": "2026-05-11T14:00:00Z"}], None),
    ]
    rx = RepoExtractor(mock_client)
    out = [item async for item in rx.list_issues_and_prs("o/r", since=None)]
    assert [i["number"] for i in out] == [1, 2, 3]
    assert mock_client.get_with_link.call_count == 2
    # Only the first call carries query params.
    first_kwargs = mock_client.get_with_link.call_args_list[0].kwargs
    assert first_kwargs["params"]["state"] == "all"
    assert first_kwargs["params"]["sort"] == "updated"


async def test_list_issues_and_prs_passes_since_iso_to_first_page(mock_client):
    mock_client.get_with_link.return_value = ([], None)
    rx = RepoExtractor(mock_client)
    since = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    _ = [i async for i in rx.list_issues_and_prs("o/r", since=since)]
    params = mock_client.get_with_link.call_args.kwargs["params"]
    assert params["since"] == "2026-05-01T00:00:00Z"


async def test_list_discussions_breaks_early_when_below_since(mock_client):
    # First page returns 3 nodes — the middle one falls below `since`, so
    # the iterator must stop *immediately* (sorted DESC means everything
    # after is older still).
    mock_client.graphql.side_effect = [
        {
            "repository": {
                "discussions": {
                    "nodes": [
                        {"number": 10, "updatedAt": "2026-05-13T10:00:00Z"},
                        {"number": 9, "updatedAt": "2026-05-12T10:00:00Z"},
                        {"number": 8, "updatedAt": "2026-04-01T10:00:00Z"},  # below
                    ],
                    "pageInfo": {"endCursor": "abc", "hasNextPage": True},
                }
            }
        },
    ]
    rx = RepoExtractor(mock_client)
    since = datetime(2026, 5, 10, 0, 0, 0, tzinfo=timezone.utc)
    out = [n async for n in rx.list_discussions("o/r", since=since)]
    assert [n["number"] for n in out] == [10, 9]
    # Must not request a second page after the cutoff.
    assert mock_client.graphql.call_count == 1


async def test_list_discussions_paginates_until_has_next_false(mock_client):
    mock_client.graphql.side_effect = [
        {"repository": {"discussions": {
            "nodes": [{"number": 1, "updatedAt": "2026-05-13T10:00:00Z"}],
            "pageInfo": {"endCursor": "page2", "hasNextPage": True},
        }}},
        {"repository": {"discussions": {
            "nodes": [{"number": 2, "updatedAt": "2026-05-12T10:00:00Z"}],
            "pageInfo": {"endCursor": None, "hasNextPage": False},
        }}},
    ]
    rx = RepoExtractor(mock_client)
    out = [n async for n in rx.list_discussions("o/r", since=None)]
    assert [n["number"] for n in out] == [1, 2]


async def test_get_readme_doc_returns_none_on_404(mock_client):
    from src.harvester.github.client import GitHubAPIError

    async def get(path):
        if "readme" in path:
            raise GitHubAPIError("Not Found", status_code=404)
        return {"updated_at": "...", "default_branch": "main"}

    mock_client.get.side_effect = get
    rx = RepoExtractor(mock_client)
    assert await rx.get_readme_doc("o/r") is None
