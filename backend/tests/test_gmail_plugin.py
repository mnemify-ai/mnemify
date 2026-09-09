"""Tests for :class:`src.harvester.gmail.plugin.GmailHarvesterPlugin`.

Mirrors the structure of ``test_jira_plugin.py``: scaffold invariants,
SourcePlugin contract assertions, factory round-trip via the registry,
and the per-method semantics with a mocked :class:`GmailClient`.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from src.harvester.gmail import (
    GmailConfig,
    GmailHarvesterPlugin,
)
from src.harvester.gmail.client import GmailAuthError, GmailClient
from src.harvester.registry import create_plugin, registered_source_types


# ── Helpers / fixtures ────────────────────────────────────────────


def _make_plugin() -> tuple[GmailHarvesterPlugin, AsyncMock]:
    cfg = GmailConfig()
    mock_client = AsyncMock(spec=GmailClient)
    plugin = GmailHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _thread_payload(
    thread_id: str = "t1",
    *,
    subject: str = "Hello",
    from_h: str = "Amy <amy@acme.com>",
    body_text: str = "hi there",
    label_ids: list[str] | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """Build a minimal full-thread payload."""
    parts = [
        {"mimeType": "text/plain", "body": {"data": _b64url(body_text)}}
    ]
    for att in attachments or ():
        parts.append(
            {
                "mimeType": att.get("mime_type", "application/pdf"),
                "filename": att["filename"],
                "body": {
                    "attachmentId": att["id"],
                    "size": att.get("size", 1024),
                },
            }
        )

    msg = {
        "id": "m1",
        "internalDate": "1745520000000",
        "labelIds": label_ids or ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed" if (attachments or []) else "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_h},
                {"name": "To", "value": "you@example.com"},
            ],
            "parts": parts,
        },
    }
    return {
        "id": thread_id,
        "historyId": "h-1",
        "snippet": body_text,
        "messages": [msg],
    }


# ── 1. Scaffold invariants ────────────────────────────────────────


def test_gmail_module_importable():
    import src.harvester.gmail  # noqa: F401


def test_gmail_public_names_exported():
    from src.harvester import gmail

    for name in (
        "GmailConfig",
        "GmailClient",
        "GmailAPIError",
        "GmailAuthError",
        "ThreadExtractor",
        "GmailHarvesterPlugin",
    ):
        assert hasattr(gmail, name), f"Expected {name!r} in src.harvester.gmail"


def test_gmail_registered_in_plugin_registry():
    assert "gmail" in registered_source_types()


def test_plugin_is_source_plugin_subclass():
    assert issubclass(GmailHarvesterPlugin, SourcePlugin)


def test_plugin_is_instantiable_without_client():
    """Smoke construction without a real client must not raise."""
    cfg = GmailConfig()
    plugin = GmailHarvesterPlugin(cfg)
    assert plugin.SOURCE_TYPE == "gmail"


def test_factory_roundtrip_via_registry(monkeypatch, tmp_path):
    """Factory works end-to-end when credentials are findable.

    Provides a real creds file via the env var so ``resolve_client_secrets_path``
    has something concrete to land on (its first action is an existence
    check on whichever path it picks).
    """
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(creds))
    plugin, closeable = create_plugin("gmail", {})
    assert isinstance(plugin, GmailHarvesterPlugin)
    assert closeable is None


def test_factory_raises_when_neither_env_nor_bundle_available(monkeypatch, tmp_path):
    """No env var AND no bundled client → factory raises and names both."""
    from src.harvester._google import oauth as google_oauth

    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)
    bundle = tmp_path / "oauth_client.json"
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundle)
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("gmail", {})
    msg = str(excinfo.value)
    assert "GMAIL_CREDENTIALS_PATH" in msg
    assert str(bundle) in msg


# ── 2. test_connection contract ──────────────────────────────────


async def test_test_connection_healthy_on_profile_success():
    plugin, mock = _make_plugin()
    mock.get_profile.return_value = {
        "emailAddress": "you@example.com",
        "messagesTotal": 100,
        "threadsTotal": 50,
    }
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy is True
    assert health.source_type == "gmail"
    assert "you@example.com" in health.message
    assert health.details["emailAddress"] == "you@example.com"
    mock.get_profile.assert_awaited_once()


async def test_test_connection_unhealthy_on_auth_error():
    plugin, mock = _make_plugin()
    mock.get_profile.side_effect = GmailAuthError("Unauthorized", status_code=401)
    health = await plugin.test_connection()
    assert health.healthy is False
    assert "mnemify login" in health.message


async def test_test_connection_unhealthy_on_generic_error():
    plugin, mock = _make_plugin()
    mock.get_profile.side_effect = RuntimeError("boom")
    health = await plugin.test_connection()
    assert health.healthy is False
    assert "boom" in health.message


# ── 3. list_documents contract ───────────────────────────────────


async def test_list_documents_emits_docrefs_with_thread_metadata():
    plugin, mock = _make_plugin()
    mock.list_threads.return_value = {
        "threads": [
            {"id": "t1", "snippet": "first thread"},
            {"id": "t2", "snippet": "second thread"},
        ]
    }

    refs = await plugin.list_documents()

    assert len(refs) == 2
    assert all(isinstance(r, DocRef) for r in refs)
    first = refs[0]
    assert first.source_id == "t1"
    assert first.source_type == "gmail"
    assert first.title == "first thread"
    assert first.metadata == {"document_type": "thread"}


async def test_list_documents_drops_threads_without_id():
    plugin, mock = _make_plugin()
    mock.list_threads.return_value = {
        "threads": [{"id": "t1", "snippet": "ok"}, {"snippet": "no id"}]
    }
    refs = await plugin.list_documents()
    assert [r.source_id for r in refs] == ["t1"]


async def test_list_documents_passes_since_to_query():
    """A ``since`` datetime turns into an ``after:`` clause in the query."""
    from datetime import datetime

    plugin, mock = _make_plugin()
    mock.list_threads.return_value = {"threads": []}

    await plugin.list_documents(since=datetime(2026, 4, 22, 0, 0))

    call_kwargs = mock.list_threads.await_args.kwargs
    call_args = mock.list_threads.await_args.args
    query = call_args[0] if call_args else call_kwargs.get("query", "")
    assert "after:" in query


# ── 4. fetch_document contract ───────────────────────────────────


async def test_fetch_document_returns_raw_document_with_format_json():
    plugin, mock = _make_plugin()
    mock.get_thread.return_value = _thread_payload(thread_id="t1")
    doc_ref = DocRef(source_id="t1", title="snippet", source_type="gmail")

    raw = await plugin.fetch_document(doc_ref)

    assert isinstance(raw, RawDocument)
    assert raw.source_id == "t1"
    assert raw.format == "json"
    # Content is valid JSON of the thread
    parsed = json.loads(raw.content)
    assert parsed["id"] == "t1"


async def test_fetch_document_metadata_carries_required_keys():
    plugin, mock = _make_plugin()
    mock.get_thread.return_value = _thread_payload(
        thread_id="t1",
        subject="Project kickoff",
        from_h="Amy <amy@acme.com>",
        label_ids=["INBOX", "Acme/Renewal"],
    )
    doc_ref = DocRef(source_id="t1", title="x", source_type="gmail")

    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    assert md["document_type"] == "thread"
    assert md["subject"] == "Project kickoff"
    assert md["from_addr"] == "amy@acme.com"
    assert md["from_name"] == "Amy"
    assert "INBOX" in md["labels"]
    assert md["thread_id"] == "t1"
    assert md["url"] == "https://mail.google.com/mail/u/0/#inbox/t1"
    assert md["message_count"] == 1


async def test_fetch_document_populates_attachment_refs():
    plugin, mock = _make_plugin()
    mock.get_thread.return_value = _thread_payload(
        thread_id="t1",
        attachments=[
            {"id": "att-1", "filename": "report.pdf", "mime_type": "application/pdf", "size": 2048},
        ],
    )
    doc_ref = DocRef(source_id="t1", title="x", source_type="gmail")

    raw = await plugin.fetch_document(doc_ref)

    assert len(raw.attachments) == 1
    att = raw.attachments[0]
    assert isinstance(att, AttachmentRef)
    assert att.filename == "report.pdf"
    assert att.url == "m1/att-1"  # synthetic compound key
    assert att.size == 2048


async def test_fetch_document_title_falls_back_to_doc_ref_title():
    plugin, mock = _make_plugin()
    mock.get_thread.return_value = {"id": "t1", "messages": []}
    doc_ref = DocRef(source_id="t1", title="fallback", source_type="gmail")

    raw = await plugin.fetch_document(doc_ref)

    # No subject in the empty payload → falls back to doc_ref.title
    assert raw.title == "fallback"


# ── 5. fetch_attachment contract ─────────────────────────────────


async def test_fetch_attachment_unpacks_compound_url():
    plugin, mock = _make_plugin()
    mock.get_attachment.return_value = b"PDF bytes"
    att = AttachmentRef(
        source_id="t1", filename="x.pdf", url="m1/att-1", mime_type="application/pdf"
    )

    out = await plugin.fetch_attachment(att)

    assert out == b"PDF bytes"
    mock.get_attachment.assert_awaited_once_with("m1", "att-1")


async def test_fetch_attachment_raises_on_malformed_url():
    plugin, _mock = _make_plugin()
    att = AttachmentRef(source_id="t1", filename="x.pdf", url="just-one-id")
    with pytest.raises(ValueError):
        await plugin.fetch_attachment(att)


# ── 6. normalize contract — pure body, no frontmatter ────────────


def test_normalize_returns_pure_body_markdown():
    plugin, _mock = _make_plugin()
    raw = RawDocument(
        source_id="t1",
        title="Hello",
        content=json.dumps(_thread_payload(thread_id="t1")).encode("utf-8"),
        format="json",
        metadata={"subject": "Hello"},
    )

    norm = plugin.normalize(raw)

    assert isinstance(norm, NormalizedDocument)
    assert norm.source_id == "t1"
    # Pure-body contract: frontmatter dict is empty AND markdown does not
    # start with the YAML delimiter.
    assert norm.frontmatter == {}
    assert not norm.markdown.startswith("---")
    assert norm.markdown.lstrip("\n").startswith("# ")
    assert norm.normalizer_version == "0.1.0"
