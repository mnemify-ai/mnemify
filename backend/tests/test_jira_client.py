"""Unit tests for :class:`src.harvester.jira.client.JiraClient` (ATL-20).

All tests mock ``atlassian.Jira`` — no network calls.  Cover:

- Happy path for each of the four public methods.
- 401 → :class:`JiraAuthError` (no retry).
- 429 → retry → success on the second attempt (tests ``Retry-After``
  parsing and the tenacity wait callable).
- Pagination smoke: caller loops ``jql_search`` advancing
  ``next_page_token`` until the response omits one.
- Empty project: JQL returning ``None`` or empty-issues dict is
  surfaced as the documented ``{"issues": []}`` shape (no ``total``
  under the enhanced JQL contract).
- Lazy construction: the ctor does not call ``atlassian.Jira``; the
  first method call does; subsequent calls reuse the instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.harvester.jira.client import (
    JiraAPIError,
    JiraAuthError,
    JiraClient,
)


# ── Helpers ──────────────────────────────────────────────────────


def _http_error(status_code: int, retry_after: str | None = None) -> requests.HTTPError:
    """Build a ``requests.HTTPError`` carrying a canned status and headers."""
    response = requests.Response()
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    err = requests.HTTPError(f"HTTP {status_code}", response=response)
    return err


@pytest.fixture
def mock_jira_cls():
    """Patch ``atlassian.Jira`` as imported by the client module."""
    with patch("src.harvester.jira.client.Jira") as mock_cls:
        yield mock_cls


# ── 1. Lazy construction ─────────────────────────────────────────


def test_ctor_does_not_construct_underlying_jira(mock_jira_cls):
    """Instantiating :class:`JiraClient` must NOT call ``atlassian.Jira``."""
    JiraClient(base_url="https://example.atlassian.net", email="e", token="t")
    assert mock_jira_cls.call_count == 0


async def test_first_method_call_constructs_jira(mock_jira_cls):
    """The first async method call constructs the underlying Jira client."""
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = {"issues": []}
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://example.atlassian.net", email="e", token="t")
    assert mock_jira_cls.call_count == 0

    await client.jql_search("project = CONN", next_page_token=None, max_results=50)
    assert mock_jira_cls.call_count == 1

    # Ctor args — basic auth via username/password, cloud=True.
    _, kwargs = mock_jira_cls.call_args
    assert kwargs["url"] == "https://example.atlassian.net"
    assert kwargs["username"] == "e"
    assert kwargs["password"] == "t"
    assert kwargs["cloud"] is True


async def test_subsequent_method_calls_reuse_client(mock_jira_cls):
    """Second and third method calls must NOT re-construct ``Jira``."""
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = {"issues": []}
    mock_instance.issue.return_value = {"key": "CONN-1"}
    mock_instance.get_all_fields.return_value = []
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://example.atlassian.net", email="e", token="t")
    await client.jql_search("project = CONN")
    await client.get_issue("CONN-1")
    await client.list_fields()

    assert mock_jira_cls.call_count == 1


# ── 2. Happy paths ───────────────────────────────────────────────


async def test_jql_search_happy_path(mock_jira_cls):
    payload = {
        "issues": [{"key": "CONN-1"}, {"key": "CONN-2"}],
        "nextPageToken": "tok-2",
    }
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = payload
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.jql_search(
        "project = CONN ORDER BY updated DESC",
        fields=["summary", "status"],
        next_page_token=None,
        max_results=50,
        expand=["renderedFields"],
    )

    assert result == payload
    mock_instance.enhanced_jql.assert_called_once()
    _, kwargs = mock_instance.enhanced_jql.call_args
    # Lists are joined to comma-separated strings at the boundary.
    assert kwargs["fields"] == "summary,status"
    assert kwargs["expand"] == "renderedFields"
    assert kwargs["nextPageToken"] is None
    assert kwargs["limit"] == 50


async def test_get_issue_happy_path(mock_jira_cls):
    payload = {"key": "CONN-123", "fields": {"summary": "Hello"}}
    mock_instance = MagicMock()
    mock_instance.issue.return_value = payload
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.get_issue(
        "CONN-123",
        fields=["summary", "description"],
        expand=["renderedFields", "names"],
    )

    assert result == payload
    _, kwargs = mock_instance.issue.call_args
    assert kwargs["fields"] == "summary,description"
    assert kwargs["expand"] == "renderedFields,names"


async def test_list_fields_happy_path(mock_jira_cls):
    payload = [
        {"id": "summary", "name": "Summary"},
        {"id": "customfield_10026", "name": "Story point estimate"},
    ]
    mock_instance = MagicMock()
    mock_instance.get_all_fields.return_value = payload
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.list_fields()

    assert result == payload
    mock_instance.get_all_fields.assert_called_once()


async def test_download_attachment_happy_path(mock_jira_cls):
    """Authenticated GET through ``Jira._session``."""
    mock_response = MagicMock()
    mock_response.content = b"\x89PNG\r\n\x1a\nfake"
    mock_response.raise_for_status.return_value = None

    mock_instance = MagicMock()
    mock_instance._session.get.return_value = mock_response
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    data = await client.download_attachment(
        "https://x.atlassian.net/rest/api/3/attachment/content/1"
    )

    assert data == b"\x89PNG\r\n\x1a\nfake"
    mock_instance._session.get.assert_called_once_with(
        "https://x.atlassian.net/rest/api/3/attachment/content/1"
    )


# ── 3. Error classification ──────────────────────────────────────


async def test_401_raises_jira_auth_error(mock_jira_cls):
    """401 is terminal and surfaces as :class:`JiraAuthError`."""
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.side_effect = _http_error(401)
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    with pytest.raises(JiraAuthError) as excinfo:
        await client.jql_search("project = CONN")

    assert excinfo.value.status_code == 401
    # JiraAuthError subclasses JiraAPIError — callers can catch either.
    assert isinstance(excinfo.value, JiraAPIError)
    # 401 must NOT trigger retries.
    assert mock_instance.enhanced_jql.call_count == 1


async def test_403_raises_jira_auth_error(mock_jira_cls):
    mock_instance = MagicMock()
    mock_instance.issue.side_effect = _http_error(403)
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    with pytest.raises(JiraAuthError):
        await client.get_issue("CONN-1")
    assert mock_instance.issue.call_count == 1


async def test_404_raises_jira_api_error_not_retried(mock_jira_cls):
    """404 is a terminal :class:`JiraAPIError` — not retried, not auth."""
    mock_instance = MagicMock()
    mock_instance.issue.side_effect = _http_error(404)
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    with pytest.raises(JiraAPIError) as excinfo:
        await client.get_issue("CONN-MISSING")

    assert excinfo.value.status_code == 404
    assert not isinstance(excinfo.value, JiraAuthError)
    assert mock_instance.issue.call_count == 1


# ── 4. Retry on 429 / 5xx ────────────────────────────────────────


async def test_429_retries_then_succeeds(mock_jira_cls):
    """429 → wait (Retry-After: 0) → retry → success on second attempt."""
    payload = {"issues": []}
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.side_effect = [_http_error(429, retry_after="0"), payload]
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.jql_search("project = CONN")

    assert result == payload
    assert mock_instance.enhanced_jql.call_count == 2


async def test_500_retries_then_succeeds(mock_jira_cls):
    """5xx is retryable too — same wait path as 429."""
    payload = {"key": "CONN-1"}
    mock_instance = MagicMock()
    mock_instance.issue.side_effect = [_http_error(503, retry_after="0"), payload]
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.get_issue("CONN-1")
    assert result == payload
    assert mock_instance.issue.call_count == 2


async def test_download_attachment_retries_on_429(mock_jira_cls):
    """Attachment path uses the same classifier / retry logic."""
    retry_resp = MagicMock()
    retry_resp.raise_for_status.side_effect = _http_error(429, retry_after="0")
    retry_resp.headers = {"Retry-After": "0"}

    good_resp = MagicMock()
    good_resp.content = b"ok"
    good_resp.raise_for_status.return_value = None

    mock_instance = MagicMock()
    mock_instance._session.get.side_effect = [retry_resp, good_resp]
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    data = await client.download_attachment("https://x.atlassian.net/att/1")
    assert data == b"ok"
    assert mock_instance._session.get.call_count == 2


# ── 5. Pagination smoke ──────────────────────────────────────────


async def test_jql_search_pagination_loop(mock_jira_cls):
    """Caller-driven pagination: feed ``nextPageToken`` forward until absent."""
    page1 = {
        "issues": [{"key": f"CONN-{i}"} for i in range(100)],
        "nextPageToken": "tok-page-2",
    }
    page2 = {
        # Last page — no ``nextPageToken``.
        "issues": [{"key": f"CONN-{i}"} for i in range(100, 150)],
    }
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.side_effect = [page1, page2]
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")

    all_issues: list[dict] = []
    token: str | None = None
    while True:
        page = await client.jql_search(
            "project = CONN ORDER BY updated DESC",
            next_page_token=token,
            max_results=100,
        )
        all_issues.extend(page["issues"])
        token = page.get("nextPageToken")
        if not token or not page["issues"]:
            break

    assert len(all_issues) == 150
    assert mock_instance.enhanced_jql.call_count == 2
    # Second call fed the page1 token forward as ``nextPageToken``.
    second_call_kwargs = mock_instance.enhanced_jql.call_args_list[1].kwargs
    assert second_call_kwargs["nextPageToken"] == "tok-page-2"


# ── 6. Empty-project contract ────────────────────────────────────


async def test_empty_project_returns_empty_issues(mock_jira_cls):
    """An empty project must surface as ``{"issues": []}`` (no ``total`` in new API)."""
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = {"issues": []}
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.jql_search("project = EMPTY")

    assert result["issues"] == []
    # Enhanced JQL omits ``total`` / ``startAt`` / ``maxResults`` —
    # pagination is driven solely by ``nextPageToken``.
    assert "total" not in result
    assert result.get("nextPageToken") is None


async def test_jql_none_response_normalised_to_empty(mock_jira_cls):
    """Library returns ``Optional[dict]``; ``None`` is normalised at boundary."""
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = None
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    result = await client.jql_search(
        "project = DELETED", next_page_token="tok-from-caller", max_results=50
    )

    # None from the library is normalised to the documented
    # empty-project shape — ``{"issues": []}`` — regardless of the
    # caller's pagination kwargs.
    assert result == {"issues": []}


# ── 7. aclose is idempotent / safe pre-construction ──────────────


async def test_aclose_before_any_method_is_safe(mock_jira_cls):
    """Calling ``aclose`` without any prior method call must not raise."""
    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    await client.aclose()
    assert mock_jira_cls.call_count == 0


async def test_aclose_after_use_closes_session(mock_jira_cls):
    mock_instance = MagicMock()
    mock_instance.enhanced_jql.return_value = {"issues": []}
    mock_jira_cls.return_value = mock_instance

    client = JiraClient(base_url="https://x.atlassian.net", email="e", token="t")
    await client.jql_search("project = CONN")
    await client.aclose()

    mock_instance.close.assert_called_once()
