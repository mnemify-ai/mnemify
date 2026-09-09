"""Tests for src.harvester.github.client — REST/GraphQL + rate-limit retry semantics."""

from __future__ import annotations

import time

import httpx
import pytest

from src.harvester.github.client import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubClient,
    GitHubRateLimitError,
    _RetryableGitHubError,
    _classify_response,
    _parse_retry_after,
)


# ── _classify_response ────────────────────────────────────────────


def _resp(status: int, *, headers: dict | None = None, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        json=json_body or {},
    )


def test_401_classified_as_auth_error():
    out = _classify_response(_resp(401, json_body={"message": "Bad credentials"}), {"message": "Bad credentials"})
    assert isinstance(out, GitHubAuthError)


def test_403_with_zero_remaining_classified_as_primary_ratelimit():
    future = int(time.time()) + 30
    out = _classify_response(
        _resp(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(future)},
              json_body={"message": "API rate limit exceeded"}),
        {"message": "API rate limit exceeded"},
    )
    assert isinstance(out, GitHubRateLimitError)
    assert out.retry_after is not None
    assert 25 < out.retry_after <= 30


def test_403_secondary_rate_limit_classified_as_ratelimit():
    out = _classify_response(
        _resp(403, headers={"Retry-After": "15"},
              json_body={"message": "You have exceeded a secondary rate limit"}),
        {"message": "You have exceeded a secondary rate limit"},
    )
    assert isinstance(out, GitHubRateLimitError)
    assert out.retry_after == 15.0


def test_terminal_403_classified_as_auth_error():
    out = _classify_response(
        _resp(403, headers={}, json_body={"message": "Resource not accessible"}),
        {"message": "Resource not accessible"},
    )
    assert isinstance(out, GitHubAuthError)


def test_429_classified_as_ratelimit_with_retry_after():
    out = _classify_response(
        _resp(429, headers={"Retry-After": "5"}, json_body={"message": "Too Many Requests"}),
        {"message": "Too Many Requests"},
    )
    assert isinstance(out, GitHubRateLimitError)
    assert out.retry_after == 5.0


def test_500_classified_as_retryable_no_retry_after():
    out = _classify_response(_resp(500, json_body={"message": "Internal Server Error"}), {"message": "..."})
    assert isinstance(out, _RetryableGitHubError)
    assert not isinstance(out, GitHubAuthError)


def test_parse_retry_after_parses_numeric_only():
    assert _parse_retry_after("30") == 30.0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("not-a-number") is None


# ── Real HTTP behaviour via MockTransport ─────────────────────────


async def test_get_with_link_parses_next_url():
    captured_calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_calls.append(str(request.url))
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"id": 3}])
        return httpx.Response(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={
                "Link": '<https://api.github.com/repos/o/r/issues?page=2>; rel="next", '
                        '<https://api.github.com/repos/o/r/issues?page=5>; rel="last"',
            },
        )

    client = GitHubClient(token="ghp_test")
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer ghp_test"},
    )

    body, next_url = await client.get_with_link("/repos/o/r/issues")
    assert isinstance(body, list) and len(body) == 2
    assert next_url == "https://api.github.com/repos/o/r/issues?page=2"

    body2, next_url2 = await client.get_with_link(next_url)
    assert body2 == [{"id": 3}]
    assert next_url2 is None
    await client.aclose()


async def test_401_translates_to_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = GitHubClient(token="ghp_bad")
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer ghp_bad"},
    )
    with pytest.raises(GitHubAuthError):
        await client.get("/user")
    await client.aclose()


async def test_graphql_errors_array_translates_to_typed_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": None,
            "errors": [{"message": "Resource not accessible by personal access token"}],
        })

    client = GitHubClient(token="ghp_test")
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer ghp_test"},
    )
    with pytest.raises(GitHubAuthError):
        await client.graphql("query{viewer{login}}", {})
    await client.aclose()


async def test_graphql_generic_error_translates_to_apierror():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None, "errors": [{"message": "Field 'foo' doesn't exist"}]})

    client = GitHubClient(token="ghp_test")
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer ghp_test"},
    )
    with pytest.raises(GitHubAPIError):
        await client.graphql("query{x}", {})
    await client.aclose()
