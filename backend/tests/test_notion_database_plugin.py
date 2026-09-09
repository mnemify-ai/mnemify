"""Unit tests for database harvesting in NotionHarvesterPlugin.

After WS2, databases are unified inside list_documents() / fetch_document().
Tests verify the database path through those unified methods.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.harvester import DocRef, RawDocument
from src.harvester.notion.client import NotionClient
from src.harvester.notion.models import NotionDatabase, NotionDatabaseRow, NotionPage
from src.harvester.notion.plugin import NotionHarvesterPlugin

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────

DT = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)


def make_plugin() -> tuple[NotionHarvesterPlugin, MagicMock]:
    mock_client = MagicMock(spec=NotionClient)
    plugin = NotionHarvesterPlugin(mock_client)
    return plugin, mock_client


def make_database(
    database_id: str = "db-1",
    title: str = "My Database",
    property_count: int = 3,
) -> NotionDatabase:
    schema = {f"Prop{i}": {"type": "text"} for i in range(property_count)}
    return NotionDatabase(
        database_id=database_id,
        title=title,
        url=f"https://notion.so/{database_id}",
        created_at=DT,
        modified_at=DT,
        properties_schema=schema,
        parent_type="workspace",
        parent_id="workspace",
    )


def make_row(page_id: str = "row-1", title: str = "Row One") -> NotionDatabaseRow:
    return NotionDatabaseRow(
        page_id=page_id,
        title=title,
        url=f"https://notion.so/{page_id}",
        properties={"Name": title, "Status": "Active"},
        created_at=DT,
        modified_at=DT,
    )


# ── list_documents includes databases ────────────────────────────


async def test_list_documents_includes_databases_tagged_correctly():
    plugin, _ = make_plugin()
    dbs = [make_database("db-1", "Work DB"), make_database("db-2", "Personal DB")]

    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=[])),
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=dbs)),
    ):
        refs = await plugin.list_documents()

    db_refs = [r for r in refs if r.metadata.get("document_type") == "database"]
    assert len(db_refs) == 2
    assert db_refs[0].source_id == "db-1"
    assert db_refs[0].title == "Work DB"
    assert db_refs[0].source_type == "notion"


async def test_list_documents_database_metadata_includes_property_count():
    plugin, _ = make_plugin()
    db = make_database("db-1", property_count=5)

    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=[])),
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=[db])),
    ):
        refs = await plugin.list_documents()

    db_refs = [r for r in refs if r.metadata.get("document_type") == "database"]
    assert db_refs[0].metadata["property_count"] == 5


async def test_list_documents_empty_databases_returns_only_pages():
    plugin, _ = make_plugin()

    with (
        patch.object(plugin.users, "load_users", new=AsyncMock(return_value=None)),
        patch.object(plugin.pages, "list_pages", new=AsyncMock(return_value=[])),
        patch.object(plugin.databases, "list_databases", new=AsyncMock(return_value=[])),
    ):
        refs = await plugin.list_documents()

    assert refs == []


# ── fetch_document dispatches on document_type ────────────────────


async def test_fetch_document_database_branch_returns_schema_and_rows():
    plugin, _ = make_plugin()
    db = make_database("db-1")
    rows = [make_row("r1", "Row One"), make_row("r2", "Row Two")]

    doc_ref = DocRef(
        source_id="db-1",
        title="My Database",
        source_type="notion",
        metadata={"document_type": "database"},
    )

    with (
        patch.object(plugin.databases, "get_database", new=AsyncMock(return_value=db)),
        patch.object(plugin.databases, "query_database", new=AsyncMock(return_value=rows)),
    ):
        raw = await plugin.fetch_document(doc_ref)

    assert isinstance(raw, RawDocument)
    assert raw.source_id == "db-1"
    assert raw.format == "json"

    native = json.loads(raw.content)
    assert "database" in native
    assert "rows" in native
    assert native["database"]["database_id"] == "db-1"
    assert len(native["rows"]) == 2


async def test_fetch_document_database_metadata_has_row_count():
    plugin, _ = make_plugin()
    db = make_database("db-1", property_count=4)
    rows = [make_row("r1"), make_row("r2"), make_row("r3")]

    doc_ref = DocRef(
        source_id="db-1",
        title="DB",
        source_type="notion",
        metadata={"document_type": "database"},
    )

    with (
        patch.object(plugin.databases, "get_database", new=AsyncMock(return_value=db)),
        patch.object(plugin.databases, "query_database", new=AsyncMock(return_value=rows)),
    ):
        raw = await plugin.fetch_document(doc_ref)

    assert raw.metadata["row_count"] == 3
    assert raw.metadata["property_count"] == 4
    assert raw.metadata["document_type"] == "database"


async def test_fetch_document_database_has_no_attachments():
    plugin, _ = make_plugin()
    db = make_database("db-empty", property_count=2)

    doc_ref = DocRef(
        source_id="db-empty",
        title="Empty DB",
        source_type="notion",
        metadata={"document_type": "database"},
    )

    with (
        patch.object(plugin.databases, "get_database", new=AsyncMock(return_value=db)),
        patch.object(plugin.databases, "query_database", new=AsyncMock(return_value=[])),
    ):
        raw = await plugin.fetch_document(doc_ref)

    assert raw.attachments == []
    native = json.loads(raw.content)
    assert native["rows"] == []


async def test_fetch_document_page_branch_for_default_doc_ref():
    """fetch_document without document_type tag falls back to page fetch."""
    from src.harvester.notion.models import NotionBlock

    plugin, _ = make_plugin()
    page = NotionPage(
        page_id="page-1",
        title="A Page",
        url="https://notion.so/page-1",
        created_at=DT,
        modified_at=DT,
        parent_type="workspace",
        parent_id="workspace",
    )
    blocks: list[NotionBlock] = []

    doc_ref = DocRef(
        source_id="page-1",
        title="A Page",
        source_type="notion",
        # No document_type in metadata → defaults to page
    )

    with (
        patch.object(plugin.pages, "get_full_page", new=AsyncMock(return_value=(page, blocks))),
        patch.object(plugin.comments, "get_page_comments", new=AsyncMock(return_value=[])),
    ):
        raw = await plugin.fetch_document(doc_ref)

    assert raw.source_id == "page-1"
    native = json.loads(raw.content)
    assert "page" in native
    assert native["page"]["page_id"] == "page-1"


# ── normalize for databases ────────────────────────────────────────


def test_normalize_database_shape_returns_title_and_row_titles():
    plugin, _ = make_plugin()

    native = {
        "database": {
            "database_id": "db-1",
            "title": "My Tasks",
            "properties_schema": {"Name": {}, "Status": {}},
        },
        "rows": [
            {"title": "Task One"},
            {"title": "Task Two"},
        ],
    }
    content = json.dumps(native, ensure_ascii=False).encode("utf-8")
    raw = RawDocument(
        source_id="db-1",
        title="My Tasks",
        content=content,
        format="json",
        metadata={"document_type": "database"},
    )

    text = plugin.normalize(raw).markdown

    assert "My Tasks" in text
    assert "Task One" in text
    assert "Task Two" in text
    assert "Name" in text


def test_normalize_database_empty_rows():
    plugin, _ = make_plugin()

    native = {
        "database": {
            "title": "Empty DB",
            "properties_schema": {},
        },
        "rows": [],
    }
    content = json.dumps(native).encode("utf-8")
    raw = RawDocument(
        source_id="db-x",
        title="Empty DB",
        content=content,
        format="json",
        metadata={"document_type": "database"},
    )

    text = plugin.normalize(raw).markdown

    assert "Empty DB" in text
