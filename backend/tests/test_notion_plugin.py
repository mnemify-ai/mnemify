"""Unit tests for NotionHarvesterPlugin.

Tests the plugin's SourcePlugin interface methods using mocked API responses.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.harvester import AttachmentRef, DocRef, RawDocument
from src.harvester.notion.client import NotionAPIError, NotionClient, NotionRateLimitError
from src.harvester.notion.models import NotionBlock, NotionPage
from src.harvester.notion.pages import AttachmentExtractor, PageExtractor
from src.harvester.notion.plugin import NOTION_NORMALIZER_VERSION, NotionHarvesterPlugin

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────

SAMPLE_DATETIME = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)


def make_page(page_id: str = "page-1", title: str = "Test Page") -> NotionPage:
    return NotionPage(
        page_id=page_id,
        title=title,
        url=f"https://notion.so/{page_id}",
        created_at=SAMPLE_DATETIME,
        modified_at=SAMPLE_DATETIME,
        parent_type="workspace",
        parent_id="workspace",
    )


def make_blocks() -> list[NotionBlock]:
    return [
        NotionBlock(
            block_id="block-1",
            block_type="heading_1",
            text_content="Hello World",
        ),
        NotionBlock(
            block_id="block-2",
            block_type="paragraph",
            text_content="Some content here.",
        ),
        NotionBlock(
            block_id="block-3",
            block_type="image",
            file_url="https://example.com/photo.png",
            file_type="external",
            caption="A test image",
        ),
    ]


def make_plugin() -> tuple[NotionHarvesterPlugin, MagicMock]:
    """Create a plugin with a mocked client."""
    mock_client = MagicMock(spec=NotionClient)
    plugin = NotionHarvesterPlugin(mock_client)
    return plugin, mock_client


# ── test_connection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connection_success():
    plugin, mock_client = make_plugin()
    mock_client.test_connection = AsyncMock(
        return_value={"id": "bot-123", "name": "Test Bot", "type": "bot"}
    )

    health = await plugin.test_connection()

    assert health.healthy is True
    assert health.source_type == "notion"
    assert "Test Bot" in health.message
    assert health.details["bot_id"] == "bot-123"


@pytest.mark.asyncio
async def test_connection_failure():
    plugin, mock_client = make_plugin()
    mock_client.test_connection = AsyncMock(side_effect=Exception("401 Unauthorized"))

    health = await plugin.test_connection()

    assert health.healthy is False
    assert "401 Unauthorized" in health.message


# ── list_documents ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents():
    plugin, _ = make_plugin()
    pages = [make_page("p1", "Page One"), make_page("p2", "Page Two")]

    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=pages)),
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=[])),
    ):
        docs = await plugin.list_documents()

    page_docs = [d for d in docs if d.metadata.get("document_type") == "page"]
    assert len(page_docs) == 2
    assert page_docs[0].source_id == "p1"
    assert page_docs[0].title == "Page One"
    assert page_docs[0].source_type == "notion"
    assert page_docs[0].source_url == "https://notion.so/p1"
    assert page_docs[0].modified_at == SAMPLE_DATETIME
    assert page_docs[0].metadata["parent_type"] == "workspace"


@pytest.mark.asyncio
async def test_list_documents_with_since():
    plugin, _ = make_plugin()

    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=[])) as mock_list,
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=[])),
    ):
        since = datetime(2026, 4, 1, tzinfo=timezone.utc)
        docs = await plugin.list_documents(since=since)

    mock_list.assert_called_once_with(since=since)
    assert docs == []


# ── scope filtering ────────────────────────────────────────────────


def _ref(source_id: str, parent_id: str | None, *, kind: str = "page") -> DocRef:
    parent_type = "workspace" if parent_id in (None, "workspace") else "page_id"
    return DocRef(
        source_id=source_id,
        title=source_id,
        source_type="notion",
        metadata={
            "document_type": kind,
            "parent_type": parent_type,
            "parent_id": parent_id,
        },
    )


def test_filter_docs_by_scope_subtree():
    from src.harvester.notion.plugin import (
        _filter_docs_by_scope,
        _normalize_notion_id,
    )

    root = _ref("root-page-id", "workspace")
    child_a = _ref("child-a-id", "root-page-id")
    grandchild = _ref("grandchild-id", "child-a-id")
    # A "data_source" object whose parent is a database id that is NOT itself
    # in the listed set (mirrors Notion's database / data-source split).
    db_x_id = "11111111-2222-3333-4444-555555555555"
    db_y = _ref("data-source-y-id", db_x_id, kind="database")
    db_row = _ref("db-row-id", "data-source-y-id")
    unrelated = _ref("unrelated-id", "workspace")
    docs = [root, child_a, grandchild, db_y, db_row, unrelated]

    # Pick the top-level page → keep it + its whole subtree, drop the rest.
    kept, matched = _filter_docs_by_scope(docs, {_normalize_notion_id("root-page-id")})
    assert {d.source_id for d in kept} == {"root-page-id", "child-a-id", "grandchild-id"}
    assert matched == {_normalize_notion_id("root-page-id")}

    # Pick a database id that only appears as a *parent value* → keep the
    # data-source object and its row (the walk checks `current in scope`
    # before consulting the parent map).
    kept, matched = _filter_docs_by_scope(docs, {_normalize_notion_id(db_x_id)})
    assert {d.source_id for d in kept} == {"data-source-y-id", "db-row-id"}
    assert matched == {_normalize_notion_id(db_x_id)}

    # Empty scope → no restriction (returns the list unchanged).
    kept, matched = _filter_docs_by_scope(docs, set())
    assert kept is docs
    assert matched == set()

    # Dash-mismatch: a scope id without dashes still matches a dashed source_id.
    kept, _ = _filter_docs_by_scope([root, unrelated], {"rootpageid"})
    assert [d.source_id for d in kept] == ["root-page-id"]

    # A parent cycle terminates and drops both (neither in scope).
    a = _ref("a", "b")
    b = _ref("b", "a")
    kept, _ = _filter_docs_by_scope([a, b], {"zzz"})
    assert kept == []


@pytest.mark.asyncio
async def test_list_documents_respects_scope():
    mock_client = MagicMock(spec=NotionClient)
    plugin = NotionHarvesterPlugin(mock_client, scope=["root-page-id"])
    pages = [
        NotionPage(
            page_id="root-page-id", title="Root", url="https://notion.so/root",
            created_at=SAMPLE_DATETIME, modified_at=SAMPLE_DATETIME,
            parent_type="workspace", parent_id="workspace",
        ),
        NotionPage(
            page_id="child-id", title="Child", url="https://notion.so/child",
            created_at=SAMPLE_DATETIME, modified_at=SAMPLE_DATETIME,
            parent_type="page_id", parent_id="root-page-id",
        ),
        NotionPage(
            page_id="other-id", title="Other", url="https://notion.so/other",
            created_at=SAMPLE_DATETIME, modified_at=SAMPLE_DATETIME,
            parent_type="workspace", parent_id="workspace",
        ),
    ]
    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=pages)),
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=[])),
    ):
        docs = await plugin.list_documents()

    assert {d.source_id for d in docs} == {"root-page-id", "child-id"}


# ── fetch_document ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_document():
    plugin, _ = make_plugin()
    page = make_page()
    blocks = make_blocks()

    with (
        patch.object(plugin.pages, "get_full_page", new=AsyncMock(return_value=(page, blocks))),
        patch.object(plugin.comments, "get_page_comments", new=AsyncMock(return_value=[])),
    ):
        doc_ref = DocRef(
            source_id="page-1",
            title="Test Page",
            source_type="notion",
        )
        raw = await plugin.fetch_document(doc_ref)

    # Basic shape checks
    assert isinstance(raw, RawDocument)
    assert raw.source_id == "page-1"
    assert raw.title == "Test Page"
    assert raw.format == "json"

    # Content is valid JSON with page and blocks
    native = json.loads(raw.content)
    assert native["page"]["page_id"] == "page-1"
    assert len(native["blocks"]) == 3

    # Attachment refs extracted from the image block
    assert len(raw.attachments) == 1
    assert raw.attachments[0].url == "https://example.com/photo.png"
    assert raw.attachments[0].source_id == "block-3"
    assert raw.attachments[0].filename == "photo.png"

    # Metadata
    assert raw.metadata["block_count"] == 3
    assert raw.metadata["attachment_count"] == 1


# ── fetch_attachment ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_attachment():
    plugin, _ = make_plugin()
    att_ref = AttachmentRef(
        source_id="block-3",
        filename="photo.png",
        url="https://example.com/photo.png",
        mime_type="image/png",
    )

    fake_content = b"\x89PNG fake image data"
    mock_response = MagicMock()
    mock_response.content = fake_content
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        content = await plugin.fetch_attachment(att_ref)

    assert content == fake_content


# ── blocks_to_markdown ─────────────────────────────────────────────


def test_blocks_to_markdown_renders_common_block_types():
    """Headings, paragraphs, lists, todos, code, quotes, dividers all render."""
    plugin, _ = make_plugin()
    blocks = [
        NotionBlock(
            block_id="h",
            block_type="heading_2",
            data={"rich_text": [{"plain_text": "Title"}]},
            text_content="Title",
        ),
        NotionBlock(
            block_id="p",
            block_type="paragraph",
            data={"rich_text": [{"plain_text": "Hello world."}]},
            text_content="Hello world.",
        ),
        NotionBlock(
            block_id="b",
            block_type="bulleted_list_item",
            data={"rich_text": [{"plain_text": "first"}]},
            text_content="first",
        ),
        NotionBlock(
            block_id="t",
            block_type="to_do",
            data={"rich_text": [{"plain_text": "do it"}], "checked": True},
            text_content="do it",
        ),
        NotionBlock(
            block_id="c",
            block_type="code",
            data={"rich_text": [{"plain_text": "print('hi')"}], "language": "python"},
            text_content="print('hi')",
        ),
        NotionBlock(block_id="d", block_type="divider", data={}),
    ]
    md = plugin.pages.blocks_to_markdown(blocks)
    assert "## Title" in md
    assert "Hello world." in md
    assert "- first" in md
    assert "- [x] do it" in md
    assert "```python" in md and "print('hi')" in md
    assert "---" in md


def test_blocks_to_markdown_inline_annotations():
    """Bold / italic / code / link annotations on rich_text become markdown."""
    plugin, _ = make_plugin()
    blocks = [
        NotionBlock(
            block_id="p",
            block_type="paragraph",
            data={
                "rich_text": [
                    {"plain_text": "be bold", "annotations": {"bold": True}},
                    {"plain_text": " "},
                    {"plain_text": "and brave", "annotations": {"italic": True}},
                    {"plain_text": " — "},
                    {"plain_text": "click", "href": "https://example.com"},
                ]
            },
        ),
    ]
    md = plugin.pages.blocks_to_markdown(blocks)
    assert "**be bold**" in md
    assert "*and brave*" in md
    assert "[click](https://example.com)" in md


def test_blocks_to_markdown_numbered_lists_increment():
    """Sequential numbered_list_items render with incrementing indices."""
    plugin, _ = make_plugin()
    blocks = [
        NotionBlock(
            block_id=f"n{i}",
            block_type="numbered_list_item",
            data={"rich_text": [{"plain_text": f"item {i}"}]},
            text_content=f"item {i}",
        )
        for i in range(1, 4)
    ]
    md = plugin.pages.blocks_to_markdown(blocks)
    assert "1. item 1" in md
    assert "2. item 2" in md
    assert "3. item 3" in md


# ── blocks_from_json (deserialization) ─────────────────────────────


def test_blocks_from_json_roundtrip():
    """Verify blocks_to_native_json and blocks_from_json are inverses."""
    original_blocks = [
        NotionBlock(
            block_id="b1",
            block_type="paragraph",
            text_content="Top level",
            children=[
                NotionBlock(
                    block_id="b2",
                    block_type="bulleted_list_item",
                    text_content="Nested item",
                    has_children=False,
                ),
            ],
            has_children=True,
        ),
        NotionBlock(
            block_id="b3",
            block_type="image",
            file_url="https://example.com/img.jpg",
            file_type="external",
            caption="Photo",
        ),
    ]

    extractor = PageExtractor.__new__(PageExtractor)
    serialized = extractor.blocks_to_native_json(original_blocks)
    restored = PageExtractor.blocks_from_json(serialized)

    assert len(restored) == 2

    # First block with nested child
    assert restored[0].block_id == "b1"
    assert restored[0].block_type == "paragraph"
    assert restored[0].text_content == "Top level"
    assert restored[0].has_children is True
    assert len(restored[0].children) == 1
    assert restored[0].children[0].block_id == "b2"
    assert restored[0].children[0].text_content == "Nested item"

    # Image block
    assert restored[1].block_id == "b3"
    assert restored[1].file_url == "https://example.com/img.jpg"
    assert restored[1].file_type == "external"
    assert restored[1].caption == "Photo"


# ── Client error handling (WS6.4) ─────────────────────────────────


async def test_client_returns_403_raises_notion_api_error_with_status_code():
    """NotionAPIError should surface the 403 status code."""
    error = NotionAPIError(status_code=403, code="restricted_resource", message="Access denied")
    assert error.status_code == 403
    assert error.code == "restricted_resource"
    assert "403" in str(error)


async def test_client_returns_404_raises_notion_api_error():
    """NotionAPIError should surface the 404 status code."""
    error = NotionAPIError(status_code=404, code="object_not_found", message="Page not found")
    assert error.status_code == 404
    assert "404" in str(error)


def test_client_returns_429_triggers_retry_with_backoff():
    """NotionRateLimitError should carry a retry_after hint."""
    error = NotionRateLimitError(retry_after=5.0)
    assert error.status_code == 429
    assert error.retry_after == 5.0
    assert error.code == "rate_limited"


def test_client_returns_500_retries_then_fails():
    """NotionAPIError with 500 status should be constructible."""
    error = NotionAPIError(status_code=500, code="internal_server_error", message="Server error")
    assert error.status_code == 500


# ── Attachment pipeline (WS6.4) ────────────────────────────────────


async def test_download_attachment_saves_file_with_content_hash_name(tmp_path):
    """AttachmentExtractor should save downloaded files with content hash in the name."""
    from src.harvester.notion.models import NotionAttachment

    mock_client = MagicMock(spec=NotionClient)
    extractor = AttachmentExtractor(mock_client)

    att = NotionAttachment(
        block_id="block-1",
        block_type="image",
        url="https://example.com/photo.png",
        filename="photo.png",
        mime_type="image/png",
        caption="",
        source_type="external",
        parent_page_id="page-1",
    )

    fake_content = b"PNG fake image data bytes"
    mock_response = MagicMock()
    mock_response.content = fake_content
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        local_path = await extractor.download_attachment(att, tmp_path)

    assert local_path is not None
    assert local_path.exists()
    assert local_path.parent == tmp_path
    # Filename contains a content hash fragment
    assert "_" in local_path.name


async def test_download_attachment_returns_none_on_http_error(tmp_path):
    """AttachmentExtractor.download_attachment should return None on HTTP failure."""
    from src.harvester.notion.models import NotionAttachment

    mock_client = MagicMock(spec=NotionClient)
    extractor = AttachmentExtractor(mock_client)

    att = NotionAttachment(
        block_id="block-1",
        block_type="image",
        url="https://example.com/404.png",
        filename="404.png",
        mime_type="image/png",
        caption="",
        source_type="external",
        parent_page_id="page-1",
    )

    with patch("httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        result = await extractor.download_attachment(att, tmp_path)

    assert result is None


async def test_download_all_returns_manifest_with_status_per_file(tmp_path):
    """download_all returns a manifest list with downloaded status per file."""
    from src.harvester.notion.models import NotionAttachment

    mock_client = MagicMock(spec=NotionClient)
    extractor = AttachmentExtractor(mock_client)

    attachments = [
        NotionAttachment(
            block_id="b1",
            block_type="image",
            url="https://example.com/img1.png",
            filename="img1.png",
            mime_type="image/png",
            caption="",
            source_type="external",
            parent_page_id="page-1",
        ),
        NotionAttachment(
            block_id="b2",
            block_type="image",
            url="https://example.com/img2.png",
            filename="img2.png",
            mime_type="image/png",
            caption="",
            source_type="external",
            parent_page_id="page-1",
        ),
    ]

    fake_content = b"fake image bytes"
    mock_response = MagicMock()
    mock_response.content = fake_content
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_http

        manifest = await extractor.download_all(attachments, tmp_path)

    assert len(manifest) == 2
    assert all(m["downloaded"] for m in manifest)
    assert all("block_id" in m for m in manifest)


def test_find_attachments_discovers_images_in_nested_blocks():
    """find_attachments should recurse into child blocks."""
    from src.harvester.notion.pages import AttachmentExtractor

    mock_client = MagicMock(spec=NotionClient)
    extractor = AttachmentExtractor(mock_client)

    nested_image = NotionBlock(
        block_id="img-block",
        block_type="image",
        file_url="https://example.com/nested.png",
        file_type="external",
    )
    parent_block = NotionBlock(
        block_id="parent",
        block_type="column",
        has_children=True,
        children=[nested_image],
    )

    attachments = extractor.find_attachments([parent_block], parent_page_id="page-1")

    assert len(attachments) == 1
    assert attachments[0].url == "https://example.com/nested.png"
    assert attachments[0].parent_page_id == "page-1"


# ── normalize ──────────────────────────────────────────────────────


def test_normalize_page_prefers_markdown_field():
    plugin, _ = make_plugin()
    native = {
        "page": {"page_id": "p1", "title": "Test"},
        "blocks": [],
        "markdown": "# Hello\n\nBody goes here.",
        "comments": [],
    }
    raw = RawDocument(
        source_id="p1",
        title="Test",
        content=json.dumps(native).encode("utf-8"),
        format="json",
    )

    norm = plugin.normalize(raw)

    assert norm.source_id == "p1"
    assert norm.title == "Test"
    assert norm.normalizer_version == NOTION_NORMALIZER_VERSION
    assert norm.frontmatter == {}
    # No YAML header — pure body text
    assert not norm.markdown.startswith("---")
    assert "# Hello" in norm.markdown
    assert "Body goes here." in norm.markdown
    assert norm.markdown.endswith("\n")


def test_normalize_page_falls_back_to_blocks_when_no_markdown():
    plugin, _ = make_plugin()
    blocks = make_blocks()
    native = {
        "page": {"page_id": "p1", "title": "Test"},
        "blocks": plugin.pages.blocks_to_native_json(blocks),
        "markdown": None,
        "comments": [],
    }
    raw = RawDocument(
        source_id="p1",
        title="Test",
        content=json.dumps(native).encode("utf-8"),
        format="json",
    )

    norm = plugin.normalize(raw)

    assert not norm.markdown.startswith("---")
    assert "Hello World" in norm.markdown
    assert "Some content here." in norm.markdown


def test_normalize_database_produces_schema_summary():
    plugin, _ = make_plugin()
    native = {
        "database": {
            "title": "My DB",
            "properties_schema": {"Name": {"type": "title"}, "Status": {"type": "select"}},
        },
        "rows": [
            {"page_id": "r1", "title": "Row One"},
            {"page_id": "r2", "title": "Row Two"},
        ],
    }
    raw = RawDocument(
        source_id="db1",
        title="My DB",
        content=json.dumps(native).encode("utf-8"),
        format="json",
    )

    norm = plugin.normalize(raw)

    assert not norm.markdown.startswith("---")
    assert "My DB" in norm.markdown
    assert "Name" in norm.markdown
    assert "Status" in norm.markdown
    assert "Row One" in norm.markdown
    assert "Row Two" in norm.markdown


def test_normalize_page_has_no_metadata_in_body():
    """The .md body must not contain any frontmatter-style metadata."""
    plugin, _ = make_plugin()
    native = {
        "page": {
            "page_id": "p1",
            "title": "Test",
            "url": "https://notion.so/p1",
            "created_at": "2026-04-01T00:00:00Z",
            "modified_at": "2026-04-13T12:00:00Z",
        },
        "blocks": [],
        "markdown": "Actual body text.",
        "comments": [],
    }
    raw = RawDocument(
        source_id="p1",
        title="Test",
        content=json.dumps(native).encode("utf-8"),
        format="json",
    )

    norm = plugin.normalize(raw)

    assert "page_id" not in norm.markdown
    assert "https://notion.so" not in norm.markdown
    assert "created_at" not in norm.markdown
    assert norm.markdown.strip() == "Actual body text."


# ── mark_harvested (WS5) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_harvested_calls_patch_with_correct_payload():
    plugin, mock_client = make_plugin()
    mock_client.patch = AsyncMock(return_value={})

    await plugin.mark_harvested("page-abc", "2026-04-14T12:00:00+00:00", "Harvested At")

    mock_client.patch.assert_called_once()
    call_args = mock_client.patch.call_args
    assert "/pages/page-abc" in call_args[0][0]
    payload = call_args[1]["json"]
    assert "Harvested At" in payload["properties"]
    assert "date" in payload["properties"]["Harvested At"]


@pytest.mark.asyncio
async def test_mark_harvested_ignores_404():
    from src.harvester.notion.client import NotionAPIError
    plugin, mock_client = make_plugin()
    mock_client.patch = AsyncMock(
        side_effect=NotionAPIError(404, "object_not_found", "Page not found")
    )

    # Should not raise
    await plugin.mark_harvested("page-gone", "2026-04-14T12:00:00+00:00")


@pytest.mark.asyncio
async def test_mark_harvested_ignores_409():
    from src.harvester.notion.client import NotionAPIError
    plugin, mock_client = make_plugin()
    mock_client.patch = AsyncMock(
        side_effect=NotionAPIError(409, "conflict_error", "Conflict")
    )

    # Should not raise
    await plugin.mark_harvested("page-conflict", "2026-04-14T12:00:00+00:00")


@pytest.mark.asyncio
async def test_mark_harvested_propagates_other_errors():
    from src.harvester.notion.client import NotionAPIError
    plugin, mock_client = make_plugin()
    mock_client.patch = AsyncMock(
        side_effect=NotionAPIError(500, "internal_error", "Server Error")
    )

    with pytest.raises(NotionAPIError) as exc_info:
        await plugin.mark_harvested("page-err", "2026-04-14T12:00:00+00:00")

    assert exc_info.value.status_code == 500
