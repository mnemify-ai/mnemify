"""Unit tests for :class:`src.harvester.gmail.client.GmailClient`.

The Google service object is mocked via ``unittest.mock`` — we test
client semantics (lazy build, retry classification, base64url decoding
of attachments), not HTTP. The retry harness is exercised by raising
``HttpError`` from the mocked ``execute()`` and checking the exception
classification matches Jira's ``_classify_http_error`` shape.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from src.harvester.gmail.client import (
    GmailAPIError,
    GmailAuthError,
    GmailClient,
    _classify_http_error,
)


# ── HTTP error classification ───────────────────────────────────


class _FakeResp(dict):
    """Minimal stand-in for httplib2.Response — dict-like with ``.status``."""

    def __init__(self, status: int, headers: dict | None = None) -> None:
        super().__init__(headers or {})
        self.status = status


class _FakeHttpError(Exception):
    """Stand-in for googleapiclient.errors.HttpError — carries ``.resp``."""

    def __init__(self, status: int, headers: dict | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.resp = _FakeResp(status, headers)


def test_classify_401_yields_auth_error():
    err = _classify_http_error(_FakeHttpError(401))
    assert isinstance(err, GmailAuthError)
    assert err.status_code == 401


def test_classify_403_yields_auth_error():
    err = _classify_http_error(_FakeHttpError(403))
    assert isinstance(err, GmailAuthError)


def test_classify_429_yields_retryable_with_retry_after():
    from src.harvester.gmail.client import _RetryableGmailError

    err = _classify_http_error(_FakeHttpError(429, {"retry-after": "12"}))
    assert isinstance(err, _RetryableGmailError)
    assert err.retry_after == 12.0


def test_classify_500_yields_retryable_without_retry_after():
    from src.harvester.gmail.client import _RetryableGmailError

    err = _classify_http_error(_FakeHttpError(500))
    assert isinstance(err, _RetryableGmailError)
    assert err.retry_after is None


def test_classify_404_yields_generic_api_error():
    err = _classify_http_error(_FakeHttpError(404))
    assert isinstance(err, GmailAPIError)
    assert not isinstance(err, GmailAuthError)
    assert err.status_code == 404


# ── Lazy service construction ───────────────────────────────────


def test_client_does_not_build_service_at_construction():
    """Constructing a client must not touch OAuth or the network."""
    client = GmailClient("/nonexistent/creds.json", "/nonexistent/token.json")
    assert client._service is None


async def test_get_profile_lazily_builds_service_and_calls_api():
    """First call constructs the service; subsequent calls reuse it."""
    client = GmailClient("/c.json", "/t.json")

    fake_service = MagicMock()
    fake_service.users().getProfile().execute.return_value = {
        "emailAddress": "you@example.com",
        "messagesTotal": 42,
    }

    # Patch _get_service to skip the OAuth path entirely.
    with patch.object(client, "_get_service", return_value=fake_service):
        result = await client.get_profile()

    assert result["emailAddress"] == "you@example.com"


async def test_get_profile_translates_http_error_to_auth_error():
    """A 401 from googleapiclient must surface as :class:`GmailAuthError`."""
    client = GmailClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.users().getProfile().execute.side_effect = _FakeHttpError(401)

    with patch.object(client, "_get_service", return_value=fake_service):
        with pytest.raises(GmailAuthError):
            await client.get_profile()


async def test_list_threads_passes_query_and_page_token():
    client = GmailClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.users().threads().list().execute.return_value = {
        "threads": [{"id": "t1"}],
        "nextPageToken": "abc",
    }

    with patch.object(client, "_get_service", return_value=fake_service):
        out = await client.list_threads("after:123", page_token=None, max_results=50)

    assert out["threads"][0]["id"] == "t1"
    # Verify the query and pageToken were passed through. The MagicMock
    # records every call; threads().list(...) is the call we care about.
    list_call = fake_service.users().threads().list
    list_call.assert_called_with(userId="me", q="after:123", pageToken=None, maxResults=50)


async def test_get_attachment_decodes_base64url():
    """Attachment ``body.data`` is base64url-encoded; client returns raw bytes."""
    client = GmailClient("/c.json", "/t.json")
    fake_service = MagicMock()
    payload_text = b"hello world"
    encoded = base64.urlsafe_b64encode(payload_text).decode("ascii")
    fake_service.users().messages().attachments().get().execute.return_value = {
        "data": encoded,
        "size": len(payload_text),
    }

    with patch.object(client, "_get_service", return_value=fake_service):
        out = await client.get_attachment("m1", "a1")

    assert out == payload_text


async def test_get_attachment_handles_empty_data():
    client = GmailClient("/c.json", "/t.json")
    fake_service = MagicMock()
    fake_service.users().messages().attachments().get().execute.return_value = {
        "data": "",
        "size": 0,
    }
    with patch.object(client, "_get_service", return_value=fake_service):
        assert await client.get_attachment("m1", "a1") == b""
