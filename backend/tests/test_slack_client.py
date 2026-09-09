"""Tests for src.harvester.slack.client — typed errors + retry semantics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from slack_sdk.errors import SlackApiError

from src.harvester.slack.client import (
    SlackAPIError,
    SlackAuthError,
    SlackClient,
    _classify_slack_error,
    _RetryableSlackError,
    _parse_retry_after,
)


# ── _parse_retry_after ────────────────────────────────────────────


def test_parse_retry_after_int_string():
    assert _parse_retry_after("3") == 3.0


def test_parse_retry_after_none():
    assert _parse_retry_after(None) is None


def test_parse_retry_after_garbage_returns_none():
    assert _parse_retry_after("soon") is None


# ── _classify_slack_error ─────────────────────────────────────────


def _make_slack_api_error(error_code: str, status: int = 200, retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = SimpleNamespace(
        status_code=status,
        headers=headers,
        get=lambda key, default=None: {"error": error_code}.get(key, default),
    )
    return SlackApiError(message=error_code, response=response)


def test_invalid_auth_classified_as_auth_error():
    exc = _make_slack_api_error("invalid_auth", status=200)
    out = _classify_slack_error(exc)
    assert isinstance(out, SlackAuthError)
    assert out.slack_error == "invalid_auth"


def test_ratelimited_classified_as_retryable_with_retry_after():
    exc = _make_slack_api_error("ratelimited", status=429, retry_after="2")
    out = _classify_slack_error(exc)
    assert isinstance(out, _RetryableSlackError)
    assert out.retry_after == 2.0


def test_channel_not_found_classified_as_terminal_api_error():
    exc = _make_slack_api_error("channel_not_found", status=200)
    out = _classify_slack_error(exc)
    assert isinstance(out, SlackAPIError)
    assert not isinstance(out, _RetryableSlackError)
    assert not isinstance(out, SlackAuthError)


def test_5xx_status_classified_as_retryable():
    exc = _make_slack_api_error("server_error", status=503)
    out = _classify_slack_error(exc)
    assert isinstance(out, _RetryableSlackError)


# ── SlackClient public surface ────────────────────────────────────


@pytest.fixture
def fake_web_client():
    fake = MagicMock()
    return fake


def test_auth_test_returns_data(fake_web_client):
    fake_web_client.auth_test.return_value = SimpleNamespace(
        data={"ok": True, "user": "alice", "team": "Acme"},
    )
    import asyncio
    client = SlackClient(token="xoxp-test")
    client._sync = fake_web_client
    out = asyncio.run(client.auth_test())
    assert out["user"] == "alice"
    assert out["team"] == "Acme"


def test_conversations_history_passes_oldest_and_cursor(fake_web_client):
    fake_web_client.conversations_history.return_value = SimpleNamespace(
        data={"messages": [], "has_more": False},
    )
    import asyncio
    client = SlackClient(token="xoxp-test")
    client._sync = fake_web_client
    asyncio.run(client.conversations_history("C1", oldest=12345.6, cursor="next", limit=50))
    kwargs = fake_web_client.conversations_history.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["oldest"] == "12345.6"
    assert kwargs["cursor"] == "next"
    assert kwargs["limit"] == 50


def test_invalid_auth_translates_to_typed_error(fake_web_client):
    fake_web_client.auth_test.side_effect = _make_slack_api_error("invalid_auth")
    import asyncio
    client = SlackClient(token="xoxp-bad")
    client._sync = fake_web_client
    with pytest.raises(SlackAuthError):
        asyncio.run(client.auth_test())


# ── download_file (private URL with bearer header) ────────────────


async def test_download_file_injects_bearer_header():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"file bytes")

    transport = httpx.MockTransport(handler)
    client = SlackClient(token="xoxp-secret")
    client._http = httpx.AsyncClient(
        transport=transport,
        headers={"Authorization": "Bearer xoxp-secret"},
    )

    data = await client.download_file("https://files.slack.com/abc")
    assert data == b"file bytes"
    assert captured["auth"] == "Bearer xoxp-secret"
    await client.aclose()


async def test_download_file_404_returns_empty_bytes():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    client = SlackClient(token="xoxp-secret")
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer xoxp-secret"},
    )
    data = await client.download_file("https://files.slack.com/gone")
    assert data == b""
    await client.aclose()
