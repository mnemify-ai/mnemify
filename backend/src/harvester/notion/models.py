"""Data models for Notion content.

These are internal representations — they decouple our code from the raw
Notion API response shape, making it easier to evolve either side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NotionPage:
    """A Notion page with its metadata (content stored separately as block tree)."""

    page_id: str
    title: str
    url: str
    created_at: datetime | None = None
    modified_at: datetime | None = None
    parent_type: str = ""  # "workspace" | "database" | "page"
    parent_id: str = ""
    properties: dict = field(default_factory=dict)
    archived: bool = False
    created_by_id: str = ""  # Notion user ID of the page creator
    last_edited_by_id: str = ""  # Notion user ID of the last editor


@dataclass
class NotionBlock:
    """A single block in a Notion page's content tree."""

    block_id: str
    block_type: str  # "paragraph", "heading_1", "image", "code", etc.
    has_children: bool = False
    children: list[NotionBlock] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # Raw block-type-specific data

    # Extracted text content (convenience — not all blocks have text)
    text_content: str = ""

    # For image/file blocks
    file_url: str | None = None
    file_type: str | None = None  # "external" | "file" (Notion-hosted)
    caption: str = ""


@dataclass
class NotionDatabase:
    """A Notion database (the container, not its rows)."""

    database_id: str
    title: str
    url: str
    created_at: datetime | None = None
    modified_at: datetime | None = None
    properties_schema: dict = field(default_factory=dict)  # Column definitions
    parent_type: str = ""
    parent_id: str = ""


@dataclass
class NotionDatabaseRow:
    """A single row in a Notion database (which is technically a page)."""

    page_id: str
    title: str
    url: str
    properties: dict = field(default_factory=dict)  # Resolved property values
    created_at: datetime | None = None
    modified_at: datetime | None = None


@dataclass
class NotionAttachment:
    """An image or file found in a Notion page."""

    block_id: str
    block_type: str
    url: str
    filename: str
    mime_type: str | None = None
    caption: str = ""
    source_type: str = "file"  # "file" (Notion-hosted) | "external"
    parent_page_id: str = ""


@dataclass
class NotionComment:
    """A comment on a Notion page or block."""

    comment_id: str
    discussion_id: str
    parent_type: str
    parent_id: str
    created_at: datetime | None = None
    created_by: str = ""
    text: str = ""
    rich_text: list[dict] = field(default_factory=list)
