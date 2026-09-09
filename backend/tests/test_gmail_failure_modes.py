"""Edge-case tests for the Gmail plugin.

Covers paths that are easy to write the happy-path code for but easy to
break under malformed responses, OAuth failures, or unusual mailboxes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.harvester import DocRef, RawDocument
from src.harvester.gmail import GmailConfig, GmailHarvesterPlugin
from src.harvester.gmail.client import GmailAPIError, GmailAuthError, GmailClient
from src.harvester.gmail.fields import flatten_thread_fields
from src.harvester.gmail.normalizer import gmail_to_markdown
from src.harvester.registry import create_plugin


def _plugin() -> tuple[GmailHarvesterPlugin, AsyncMock]:
    cfg = GmailConfig()
    mock = AsyncMock(spec=GmailClient)
    return GmailHarvesterPlugin(cfg, client=mock), mock


# ── Auth errors during harvesting ────────────────────────────────


async def test_auth_error_during_list_propagates():
    """An expired refresh token at runtime surfaces as :class:`GmailAuthError`."""
    plugin, mock = _plugin()
    mock.list_threads.side_effect = GmailAuthError("token revoked", status_code=401)

    with pytest.raises(GmailAuthError):
        await plugin.list_documents()


async def test_api_error_during_fetch_propagates():
    plugin, mock = _plugin()
    mock.get_thread.side_effect = GmailAPIError("server error", status_code=500)
    doc = DocRef(source_id="t1", title="x", source_type="gmail")

    with pytest.raises(GmailAPIError):
        await plugin.fetch_document(doc)


# ── Malformed responses ──────────────────────────────────────────


def test_flatten_handles_missing_payload():
    """A message with no payload key shouldn't crash flatten."""
    out = flatten_thread_fields(
        {"id": "t1", "messages": [{"id": "m1", "internalDate": "1"}]}
    )
    assert out["subject"] == ""
    assert out["from_addr"] == ""


def test_flatten_handles_missing_headers():
    out = flatten_thread_fields(
        {
            "id": "t1",
            "messages": [
                {"id": "m1", "internalDate": "1", "payload": {"parts": []}}
            ],
        }
    )
    assert out["subject"] == ""


def test_normalizer_handles_messages_without_internal_date():
    """No internalDate → date heading absent but message body still rendered."""
    payload = {
        "id": "t1",
        "messages": [
            {
                "id": "m1",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hi"},
                        {"name": "From", "value": "a@x"},
                    ],
                    "body": {"data": "aGVsbG8="},  # base64('hello')
                    "mimeType": "text/plain",
                },
            }
        ],
    }
    out = gmail_to_markdown(json.dumps(payload).encode("utf-8"), {})
    assert "# Hi" in out
    # Heading falls back to "## a@x" without the date prefix
    assert "## a@x" in out


def test_normalizer_handles_thread_with_zero_messages():
    """An empty messages array yields a title-only document."""
    raw = json.dumps({"id": "t1", "messages": []}).encode("utf-8")
    out = gmail_to_markdown(raw, {"subject": "Empty"})
    assert "# Empty" in out


# ── Factory-level configuration errors ──────────────────────────


def test_factory_no_env_no_bundle_raises_with_helpful_message(monkeypatch, tmp_path):
    """Both env var unset AND no bundled client → factory raises and points at the bundle."""
    from src.harvester._google import oauth as google_oauth

    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)
    # Force the bundle path to a nonexistent location named like the
    # production file so the operator sees a recognisable hint.
    bundle = tmp_path / "oauth_client.json"
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundle)

    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("gmail", {})
    msg = str(excinfo.value)
    assert str(bundle) in msg                # operator can copy the path
    assert "GMAIL_CREDENTIALS_PATH" in msg   # power-user override is named


def test_factory_succeeds_with_bundled_client_only(monkeypatch, tmp_path):
    """No env var set, but a bundled client exists → factory succeeds (the new default)."""
    from src.harvester._google import oauth as google_oauth

    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}")
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundled)
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)

    plugin, closeable = create_plugin("gmail", {})

    assert isinstance(plugin, GmailHarvesterPlugin)
    assert closeable is None


def test_factory_credentials_path_via_config_dict(tmp_path):
    """`credentials_path` directly in config short-circuits both env and bundle."""
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    plugin, closeable = create_plugin("gmail", {"credentials_path": str(creds)})
    assert isinstance(plugin, GmailHarvesterPlugin)
    assert closeable is None


def test_factory_custom_credentials_env_resolves(monkeypatch, tmp_path):
    """An override of ``credentials_env`` redirects which env var is read."""
    creds = tmp_path / "custom-creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("MY_GMAIL_CREDS", str(creds))
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)
    plugin, _ = create_plugin("gmail", {"credentials_env": "MY_GMAIL_CREDS"})
    assert isinstance(plugin, GmailHarvesterPlugin)
