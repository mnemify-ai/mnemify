"""Tests for :class:`ConfluenceHarvesterPlugin` (ATL-13).

Modelled on ``tests/test_obsidian_plugin.py``.  Every test mocks
:class:`PageExtractor` / :class:`ConfluenceClient` at their import sites
inside ``src.harvester.confluence.plugin`` — no network, no Atlassian SDK
ever runs.  Attachment downloads are deliberately out of scope (ATL-30);
``fetch_attachment`` is only exercised as a tagged stub.

Coverage:

1. SourcePlugin contract (subclass + instantiable + source_type).
2. ``test_connection`` — healthy path via :meth:`ConfluenceClient.list_spaces`,
   unhealthy paths for auth / API errors.
3. ``list_documents`` — multi-space enumeration (delegates to
   :meth:`PageExtractor.list_pages`), DocRef shape + §3.1 metadata,
   archived filter.
4. ``fetch_document`` — RawDocument shape, XHTML body preserved as UTF-8
   bytes, §3.1 metadata populated, attachments emitted as refs, plugin
   delegates to :meth:`PageExtractor.list_page_attachments`.
5. ``fetch_attachment`` (ATL-30) — delegates to
   :meth:`ConfluenceClient.download_attachment_content`, returns bytes,
   propagates :class:`ConfluenceAuthError`/:class:`ConfluenceAPIError`.
6. ``extract_plain_text`` — round-trip via ``html_to_plain_text``.
7. ``mark_harvested`` and ``aclose`` are no-ops / safe.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.harvester import AttachmentRef, DocRef, HealthStatus, RawDocument, SourcePlugin
from src.harvester.confluence import (
    ConfluenceConfig,
    ConfluenceHarvesterPlugin,
)
from src.harvester.confluence.client import (
    ConfluenceAPIError,
    ConfluenceAuthError,
)

# ── ATL-50 fixtures ───────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "confluence"


def _load_fixture(name: str) -> dict:
    """Load a frozen Confluence REST snapshot from the ATL-50 fixture dir."""
    return json.loads((FIXTURE_DIR / name).read_text())


# ── Fixtures / helpers ───────────────────────────────────────────


def _cfg(**overrides) -> ConfluenceConfig:
    base = {
        "base_url": "https://example.atlassian.net/wiki",
        "space_keys": ["ENG", "PROD"],
    }
    base.update(overrides)
    return ConfluenceConfig(**base)


async def _as_async_iter(items: Iterable[dict]):
    for item in items:
        yield item


def _list_page(
    page_id: str,
    *,
    title: str = "Page",
    space_key: str | None = "ENG",
    when: str | None = "2026-04-18T12:00:00.000Z",
    status: str | None = None,
    webui: str = "/spaces/ENG/pages/1/Page",
) -> dict:
    out: dict = {
        "id": page_id,
        "title": title,
        "type": "page",
        "_links": {"webui": webui},
    }
    if space_key is not None:
        out["space"] = {"key": space_key}
    if when is not None:
        out["version"] = {"when": when, "number": 1}
    if status is not None:
        out["status"] = status
    return out


def _full_page(
    page_id: str,
    *,
    title: str = "Full Page",
    space_key: str = "ENG",
    body: str = "<p>Hello</p>",
    when: str = "2026-04-18T12:00:00.000Z",
    version: int = 3,
    ancestors: list[dict] | None = None,
    labels: list[str] | None = None,
    created_by_id: str = "acc-1",
    created_by_name: str = "Ava Author",
    created_date: str = "2026-04-10T09:30:00.000Z",
    webui: str = "/spaces/ENG/pages/1/Full+Page",
) -> dict:
    return {
        "id": page_id,
        "title": title,
        "type": "page",
        "space": {"key": space_key},
        "body": {"storage": {"value": body, "representation": "storage"}},
        "version": {"when": when, "number": version},
        "history": {
            "createdDate": created_date,
            "createdBy": {
                "accountId": created_by_id,
                "displayName": created_by_name,
                "type": "known",
            },
        },
        "ancestors": ancestors or [],
        "metadata": {
            "labels": {
                "results": [{"name": lbl} for lbl in (labels or [])],
            }
        },
        "_links": {"webui": webui},
    }


def _attachment(
    att_id: str,
    *,
    title: str = "diagram.png",
    media_type: str = "image/png",
    size: int = 1234,
    download: str | None = None,
) -> dict:
    return {
        "id": att_id,
        "type": "attachment",
        "title": title,
        "extensions": {"mediaType": media_type, "fileSize": size},
        "_links": {"download": download or f"/download/attachments/1/{title}"},
    }


@pytest.fixture
def mock_extractor():
    """Patch :class:`PageExtractor` at its plugin import site.

    Yields the ``MagicMock`` instance so each test can wire up
    ``list_pages`` / ``get_full_page`` / ``list_page_attachments``
    independently.
    """
    with patch("src.harvester.confluence.plugin.PageExtractor") as ctor:
        instance = MagicMock()
        instance.list_pages = MagicMock()
        instance.get_full_page = AsyncMock()
        instance.list_page_attachments = AsyncMock()
        ctor.return_value = instance
        yield instance


@pytest.fixture
def mock_client():
    """Patch :class:`ConfluenceClient` at its plugin import site."""
    with patch("src.harvester.confluence.plugin.ConfluenceClient") as ctor:
        instance = MagicMock()
        instance.list_spaces = AsyncMock()
        instance.download_attachment_content = AsyncMock()
        instance.aclose = AsyncMock(return_value=None)
        ctor.return_value = instance
        yield instance


@pytest.fixture
def plugin(mock_client, mock_extractor) -> ConfluenceHarvesterPlugin:
    return ConfluenceHarvesterPlugin(_cfg())


# ── 1. SourcePlugin contract ───────────────────────────────────────


def test_plugin_is_source_plugin_subclass():
    assert issubclass(ConfluenceHarvesterPlugin, SourcePlugin)


def test_plugin_source_type():
    assert ConfluenceHarvesterPlugin.SOURCE_TYPE == "confluence"


def test_plugin_is_instantiable(mock_client, mock_extractor):
    """All abstract methods are implemented — no ``TypeError`` on construction."""
    p = ConfluenceHarvesterPlugin(_cfg())
    assert p is not None
    assert p.config.base_url == "https://example.atlassian.net/wiki"


# ── 2. test_connection ────────────────────────────────────────────


async def test_connection_healthy_on_successful_space_list(plugin, mock_client):
    mock_client.list_spaces.return_value = {"results": [{"key": "ENG"}]}
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy
    assert health.source_type == "confluence"
    assert "Connected" in health.message
    mock_client.list_spaces.assert_awaited_once_with(limit=1)


async def test_connection_healthy_with_zero_spaces(plugin, mock_client):
    """An empty result list still means auth worked — healthy."""
    mock_client.list_spaces.return_value = {"results": []}
    health = await plugin.test_connection()
    assert health.healthy


async def test_connection_unhealthy_on_auth_error(plugin, mock_client):
    mock_client.list_spaces.side_effect = ConfluenceAuthError(
        "auth failed", status_code=401
    )
    health = await plugin.test_connection()
    assert not health.healthy
    # Remediation message names the env vars
    assert "CONFLUENCE_EMAIL" in health.message
    assert "CONFLUENCE_API_TOKEN" in health.message


async def test_connection_unhealthy_on_api_error(plugin, mock_client):
    mock_client.list_spaces.side_effect = ConfluenceAPIError(
        "500 server error", status_code=500
    )
    health = await plugin.test_connection()
    assert not health.healthy
    assert "500" in health.message or "server error" in health.message.lower()


# ── 3. list_documents ────────────────────────────────────────────


async def test_list_documents_delegates_to_page_extractor(plugin, mock_extractor):
    mock_extractor.list_pages.return_value = _as_async_iter(
        [_list_page("1"), _list_page("2")]
    )
    docs = await plugin.list_documents()
    assert len(docs) == 2
    # Confirm configured space keys are passed through
    call_args, call_kwargs = mock_extractor.list_pages.call_args
    assert call_args[0] == ["ENG", "PROD"]
    assert call_kwargs.get("since") is None


async def test_list_documents_passes_since_filter(plugin, mock_extractor):
    cutoff = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    mock_extractor.list_pages.return_value = _as_async_iter([])
    await plugin.list_documents(since=cutoff)
    _, call_kwargs = mock_extractor.list_pages.call_args
    assert call_kwargs["since"] == cutoff


async def test_list_documents_returns_doc_refs_with_required_fields(plugin, mock_extractor):
    mock_extractor.list_pages.return_value = _as_async_iter(
        [
            _list_page("42", title="Roadmap", space_key="ENG"),
        ]
    )
    docs = await plugin.list_documents()
    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, DocRef)
    assert doc.source_id == "42"
    assert doc.source_type == "confluence"
    assert doc.title == "Roadmap"
    assert doc.modified_at is not None
    assert doc.source_url is not None
    assert doc.source_url.startswith("https://example.atlassian.net/wiki")


async def test_list_documents_metadata_includes_plan_fields(plugin, mock_extractor):
    mock_extractor.list_pages.return_value = _as_async_iter(
        [_list_page("7", space_key="ENG")]
    )
    docs = await plugin.list_documents()
    md = docs[0].metadata
    assert md["document_type"] == "page"
    assert md["space_key"] == "ENG"
    assert md["url"] is not None
    assert md["updated_at"] is not None


async def test_list_documents_skips_archived_by_default(mock_client, mock_extractor):
    plugin = ConfluenceHarvesterPlugin(_cfg(include_archived=False))
    mock_extractor.list_pages.return_value = _as_async_iter(
        [
            _list_page("1", status="current"),
            _list_page("2", status="archived"),
        ]
    )
    docs = await plugin.list_documents()
    assert [d.source_id for d in docs] == ["1"]


async def test_list_documents_includes_archived_when_configured(mock_client, mock_extractor):
    plugin = ConfluenceHarvesterPlugin(_cfg(include_archived=True))
    mock_extractor.list_pages.return_value = _as_async_iter(
        [
            _list_page("1", status="current"),
            _list_page("2", status="archived"),
        ]
    )
    docs = await plugin.list_documents()
    assert sorted(d.source_id for d in docs) == ["1", "2"]


async def test_list_documents_drops_entries_without_id(plugin, mock_extractor):
    mock_extractor.list_pages.return_value = _as_async_iter(
        [
            _list_page("1"),
            {"title": "no-id", "type": "page"},  # dropped
            _list_page("3"),
        ]
    )
    docs = await plugin.list_documents()
    assert [d.source_id for d in docs] == ["1", "3"]


async def test_list_documents_empty_when_no_pages(plugin, mock_extractor):
    mock_extractor.list_pages.return_value = _as_async_iter([])
    docs = await plugin.list_documents()
    assert docs == []


# ── 4. fetch_document ────────────────────────────────────────────


async def test_fetch_document_returns_raw_document(plugin, mock_extractor):
    mock_extractor.get_full_page.return_value = _full_page(
        "100",
        body="<p>Body</p>",
    )
    mock_extractor.list_page_attachments.return_value = []
    doc_ref = DocRef(source_id="100", title="Hint", source_type="confluence")

    raw = await plugin.fetch_document(doc_ref)

    assert isinstance(raw, RawDocument)
    assert raw.source_id == "100"
    assert raw.format == "html"
    assert raw.content == b"<p>Body</p>"


async def test_fetch_document_preserves_xhtml_bytes_as_utf8(plugin, mock_extractor):
    xhtml = "<p>café — 你好 🌍</p>"
    mock_extractor.get_full_page.return_value = _full_page("1", body=xhtml)
    mock_extractor.list_page_attachments.return_value = []

    raw = await plugin.fetch_document(DocRef("1", "t", "confluence"))

    assert raw.content == xhtml.encode("utf-8")
    assert raw.content.decode("utf-8") == xhtml


async def test_fetch_document_metadata_has_plan_fields(plugin, mock_extractor):
    mock_extractor.get_full_page.return_value = _full_page(
        "1",
        space_key="ENG",
        ancestors=[
            {"id": "root", "title": "Root"},
            {"id": "mid", "title": "Middle"},
        ],
        labels=["design", "rfc"],
        version=7,
        created_by_id="acc-42",
        created_by_name="Ava Author",
    )
    mock_extractor.list_page_attachments.return_value = [
        _attachment("a1"),
        _attachment("a2", title="spec.pdf", media_type="application/pdf"),
    ]

    raw = await plugin.fetch_document(DocRef("1", "t", "confluence"))
    md = raw.metadata

    required_keys = {
        "document_type",
        "url",
        "space_key",
        "version_number",
        "author_id",
        "author_name",
        "created_at",
        "updated_at",
        "parent_id",
        "parent_title",
        "ancestors",
        "labels",
        "attachment_count",
    }
    assert required_keys.issubset(md.keys())
    assert md["document_type"] == "page"
    assert md["space_key"] == "ENG"
    assert md["version_number"] == 7
    assert md["author_id"] == "acc-42"
    assert md["author_name"] == "Ava Author"
    assert md["created_at"] is not None
    assert md["updated_at"] is not None
    # Parent is the deepest ancestor
    assert md["parent_id"] == "mid"
    assert md["parent_title"] == "Middle"
    assert md["ancestors"] == [
        {"id": "root", "title": "Root"},
        {"id": "mid", "title": "Middle"},
    ]
    assert md["labels"] == ["design", "rfc"]
    assert md["attachment_count"] == 2


async def test_fetch_document_no_ancestors_yields_null_parent(plugin, mock_extractor):
    mock_extractor.get_full_page.return_value = _full_page("1", ancestors=[])
    mock_extractor.list_page_attachments.return_value = []

    raw = await plugin.fetch_document(DocRef("1", "t", "confluence"))

    assert raw.metadata["parent_id"] is None
    assert raw.metadata["parent_title"] is None
    assert raw.metadata["ancestors"] == []


async def test_fetch_document_emits_attachment_refs(plugin, mock_extractor):
    mock_extractor.get_full_page.return_value = _full_page("42")
    mock_extractor.list_page_attachments.return_value = [
        _attachment("a1", title="diagram.png", media_type="image/png", size=500),
    ]

    raw = await plugin.fetch_document(DocRef("42", "t", "confluence"))

    assert len(raw.attachments) == 1
    att = raw.attachments[0]
    assert isinstance(att, AttachmentRef)
    assert att.source_id == "42"  # parent page id for sharding
    assert att.filename == "diagram.png"
    assert att.mime_type == "image/png"
    assert att.size == 500
    assert att.url == (
        "https://example.atlassian.net/wiki/rest/api/content/"
        "42/child/attachment/a1/download"
    )


async def test_fetch_document_absolute_attachment_url_is_preserved(plugin, mock_extractor):
    """If Atlassian ever returns an absolute URL in ``_links.download``, keep it."""
    mock_extractor.get_full_page.return_value = _full_page("42")
    absolute = "https://other.cdn/attachments/a1.png"
    mock_extractor.list_page_attachments.return_value = [
        _attachment("a1", download=absolute),
    ]

    raw = await plugin.fetch_document(DocRef("42", "t", "confluence"))
    assert raw.attachments[0].url == absolute


async def test_fetch_document_drops_attachments_without_download_url(plugin, mock_extractor):
    mock_extractor.get_full_page.return_value = _full_page("42")
    broken = {"id": "a1", "title": "lost", "_links": {}}
    mock_extractor.list_page_attachments.return_value = [broken]

    raw = await plugin.fetch_document(DocRef("42", "t", "confluence"))
    assert raw.attachments == []
    assert raw.metadata["attachment_count"] == 0


async def test_fetch_document_uses_body_storage_value(plugin, mock_extractor):
    """Only body.storage.value is stored — nested keys must not leak."""
    page = _full_page("1", body="")
    page["body"]["storage"]["value"] = "<h1>Title</h1>"
    mock_extractor.get_full_page.return_value = page
    mock_extractor.list_page_attachments.return_value = []

    raw = await plugin.fetch_document(DocRef("1", "t", "confluence"))
    assert raw.content == b"<h1>Title</h1>"


async def test_fetch_document_missing_body_is_empty_bytes(plugin, mock_extractor):
    page = _full_page("1")
    del page["body"]
    mock_extractor.get_full_page.return_value = page
    mock_extractor.list_page_attachments.return_value = []

    raw = await plugin.fetch_document(DocRef("1", "t", "confluence"))
    assert raw.content == b""


# ── 4b. fetch_document <-> list_page_attachments delegation ──────


async def test_fetch_document_delegates_to_list_page_attachments(plugin, mock_extractor):
    """Plugin must call :meth:`PageExtractor.list_page_attachments` with
    the page id — the plan-doc seam that keeps attachment enumeration
    out of ``get_full_page``'s response shape."""
    mock_extractor.get_full_page.return_value = _full_page("555")
    mock_extractor.list_page_attachments.return_value = [
        _attachment("a1", title="d.png"),
    ]

    await plugin.fetch_document(DocRef("555", "t", "confluence"))

    mock_extractor.list_page_attachments.assert_awaited_once_with("555")


# ── 5. fetch_attachment (ATL-30) ──────────────────────────────────


async def test_fetch_attachment_delegates_to_client_download(plugin, mock_client):
    """Plugin calls :meth:`ConfluenceClient.download_attachment_content`
    with the ref's absolute URL — no rewriting, no HTTP client of its own."""
    mock_client.download_attachment_content.return_value = b"binary-payload"
    url = "https://example.atlassian.net/wiki/download/attachments/1/diagram.png"
    ref = AttachmentRef(
        source_id="1",
        filename="diagram.png",
        url=url,
        mime_type="image/png",
        size=1234,
    )

    data = await plugin.fetch_attachment(ref)

    assert data == b"binary-payload"
    mock_client.download_attachment_content.assert_awaited_once_with(url)


async def test_fetch_attachment_returns_bytes_passthrough(plugin, mock_client):
    """Exact byte identity is preserved — no re-encoding, no framing."""
    payload = bytes(range(256))  # arbitrary binary, includes 0x00, 0xFF
    mock_client.download_attachment_content.return_value = payload
    ref = AttachmentRef(source_id="1", filename="blob.bin", url="https://x/blob")

    data = await plugin.fetch_attachment(ref)

    assert data is payload or data == payload


async def test_fetch_attachment_propagates_auth_error(plugin, mock_client):
    """401/403 from the client must surface so the orchestrator's loop
    (``orchestrator.py:307-352``, catches bare ``Exception``) logs and
    continues to the next attachment rather than silently succeeding."""
    mock_client.download_attachment_content.side_effect = ConfluenceAuthError(
        "auth failed", status_code=401
    )
    ref = AttachmentRef(source_id="1", filename="x.png", url="https://x/x.png")

    with pytest.raises(ConfluenceAuthError):
        await plugin.fetch_attachment(ref)


async def test_fetch_attachment_propagates_api_error(plugin, mock_client):
    """Non-auth API failures (e.g. 404 deleted attachment) propagate."""
    mock_client.download_attachment_content.side_effect = ConfluenceAPIError(
        "not found", status_code=404
    )
    ref = AttachmentRef(source_id="1", filename="x.png", url="https://x/x.png")

    with pytest.raises(ConfluenceAPIError):
        await plugin.fetch_attachment(ref)


# ── 7. mark_harvested / aclose are no-ops ────────────────────────


async def test_mark_harvested_is_noop(plugin):
    # Inherited ABC default — should not raise.
    await plugin.mark_harvested("some-id", "2026-04-15T00:00:00Z")


async def test_aclose_awaits_client_aclose(plugin, mock_client):
    await plugin.aclose()
    mock_client.aclose.assert_awaited_once()


# ── 8. ATL-51 fixture-backed coverage ────────────────────────────
#
# These exercises feed real-Atlassian-shaped JSON (from ATL-50) through
# the plugin.  They complement the inline-helper cases above by making
# sure the plugin handles the exact envelope the REST client returns,
# not just the helper-builder's projection.


async def test_list_documents_against_frozen_list_fixture(mock_client, mock_extractor):
    """Feed the ATL-50 five-page envelope through list_documents.

    Verifies the plugin projects each fixture entry into a
    :class:`DocRef` with the plan §3.1 list-time metadata populated.
    Pairs the list-envelope fixture with the plugin by surfacing the
    ``results`` array through the patched :class:`PageExtractor`.
    """
    envelope = _load_fixture("list_pages_response.json")
    assert len(envelope["results"]) == 5  # sanity-gate the fixture

    mock_extractor.list_pages.return_value = _as_async_iter(envelope["results"])

    plugin = ConfluenceHarvesterPlugin(_cfg())
    docs = await plugin.list_documents()

    # All five fixture pages surface (none are archived in this envelope)
    assert {d.source_id for d in docs} == {"100", "101", "102", "103", "104"}
    titles = {d.source_id: d.title for d in docs}
    assert titles["101"] == "Roadmap 2026"

    # Metadata carries the plan §3.1 list-time keys
    roadmap = next(d for d in docs if d.source_id == "101")
    assert roadmap.metadata["document_type"] == "page"
    assert roadmap.metadata["space_key"] == "ENG"
    assert roadmap.metadata["updated_at"] is not None
    assert roadmap.source_url.startswith("https://example.atlassian.net/wiki")


async def test_list_documents_filters_archived_with_fixture(mock_client, mock_extractor):
    """ATL-51 row: ``include_archived: false`` strips ``status == 'archived'``.

    Uses the archived-mixed fixture so the status field flows in at the
    exact byte shape Atlassian Cloud emits — guards against a regression
    where the plugin stops looking at the top-level ``status`` field.
    """
    envelope = _load_fixture("list_pages_archived.json")
    # Fixture must contain at least one archived + one current to be useful
    statuses = {p.get("status") for p in envelope["results"]}
    assert {"current", "archived"}.issubset(statuses)

    mock_extractor.list_pages.return_value = _as_async_iter(envelope["results"])
    plugin = ConfluenceHarvesterPlugin(_cfg(include_archived=False))
    docs = await plugin.list_documents()

    # Only the "current" pages survive
    assert [d.source_id for d in docs] == ["200"]
    # And no document_type=page + status=archived leaked through
    for d in docs:
        assert d.metadata.get("status") != "archived"


async def test_list_documents_include_archived_with_fixture(mock_client, mock_extractor):
    """When ``include_archived=True``, the archived rows survive end-to-end."""
    envelope = _load_fixture("list_pages_archived.json")
    mock_extractor.list_pages.return_value = _as_async_iter(envelope["results"])

    plugin = ConfluenceHarvesterPlugin(_cfg(include_archived=True))
    docs = await plugin.list_documents()

    assert sorted(d.source_id for d in docs) == ["200", "201", "202"]
    # At least one archived row carries status through to metadata
    assert any(d.metadata.get("status") == "archived" for d in docs)


async def test_fetch_document_against_ancestors_fixture(mock_client, mock_extractor):
    """Full-page fetch against the ATL-50 ancestor chain fixture.

    Asserts the ancestor list → parent projection (plan §3.1) works on
    the real REST envelope shape: ``ancestors: [{id, title}, ...]``,
    deepest-last.
    """
    full_page = _load_fixture("page_with_ancestors.json")
    mock_extractor.get_full_page.return_value = full_page
    mock_extractor.list_page_attachments.return_value = []

    plugin = ConfluenceHarvesterPlugin(_cfg())
    raw = await plugin.fetch_document(DocRef("101", "hint", "confluence"))

    md = raw.metadata
    # Three ancestors — deepest (2026) is the parent
    assert [a["id"] for a in md["ancestors"]] == ["1", "10", "50"]
    assert md["parent_id"] == "50"
    assert md["parent_title"] == "2026"
    # Labels from the fixture surfaced in order
    assert md["labels"] == ["planning", "roadmap", "strategy"]
    assert md["version_number"] == 12
    assert md["space_key"] == "ENG"
    # Body was stored exactly as authored
    assert raw.content == full_page["body"]["storage"]["value"].encode("utf-8")


async def test_fetch_document_against_attachments_fixture(mock_client, mock_extractor):
    """Two-attachment fixture surfaces both refs with absolute URLs."""
    full_page = _load_fixture("page_with_attachments.json")
    atts_envelope = _load_fixture("attachments_response.json")
    mock_extractor.get_full_page.return_value = full_page
    mock_extractor.list_page_attachments.return_value = atts_envelope["results"]

    plugin = ConfluenceHarvesterPlugin(_cfg())
    raw = await plugin.fetch_document(DocRef("100", "hint", "confluence"))

    assert len(raw.attachments) == 2
    assert raw.metadata["attachment_count"] == 2
    # Every ref carries the parent page id for sharding
    assert all(att.source_id == "100" for att in raw.attachments)
    # Filenames survive
    assert {att.filename for att in raw.attachments} == {"diagram.png", "spec.pdf"}
    # Each ref points at the REST-API content-download endpoint for
    # its (page, attachment) pair — the path that accepts basic auth.
    urls_by_filename = {att.filename: att.url for att in raw.attachments}
    assert urls_by_filename["diagram.png"] == (
        "https://example.atlassian.net/wiki/rest/api/content/"
        "100/child/attachment/att-1/download"
    )
    assert urls_by_filename["spec.pdf"] == (
        "https://example.atlassian.net/wiki/rest/api/content/"
        "100/child/attachment/att-2/download"
    )
