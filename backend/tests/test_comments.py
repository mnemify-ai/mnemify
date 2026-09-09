"""Unit tests for CommentExtractor (src/harvester/notion/comments.py)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


from src.harvester.notion.client import NotionClient
from src.harvester.notion.comments import CommentExtractor
from src.harvester.notion.models import NotionComment

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────


def make_extractor() -> tuple[CommentExtractor, MagicMock]:
    """Return a CommentExtractor with a mocked client."""
    mock_client = MagicMock(spec=NotionClient)
    extractor = CommentExtractor(mock_client)
    return extractor, mock_client


def make_raw_comment(
    comment_id: str = "comment-1",
    discussion_id: str = "disc-1",
    parent_type: str = "page_id",
    parent_value: str = "page-abc",
    plain_text: str = "This looks great!",
    created_by_id: str = "user-123",
    created_time: str = "2026-04-10T10:00:00.000Z",
) -> dict:
    return {
        "id": comment_id,
        "discussion_id": discussion_id,
        "parent": {
            "type": parent_type,
            parent_type: parent_value,
        },
        "rich_text": [{"plain_text": plain_text, "type": "text"}],
        "created_by": {"id": created_by_id},
        "created_time": created_time,
    }


# ── get_page_comments ──────────────────────────────────────────────


async def test_get_page_comments_returns_parsed_comment_objects():
    extractor, mock_client = make_extractor()
    raw = make_raw_comment()
    mock_client.paginate = AsyncMock(return_value=[raw])

    result = await extractor.get_page_comments("page-abc")

    assert len(result) == 1
    assert isinstance(result[0], NotionComment)
    assert result[0].comment_id == "comment-1"
    assert result[0].text == "This looks great!"
    assert result[0].created_by == "user-123"


async def test_get_page_comments_calls_paginate_with_block_id():
    extractor, mock_client = make_extractor()
    mock_client.paginate = AsyncMock(return_value=[])

    await extractor.get_page_comments("page-xyz")

    mock_client.paginate.assert_called_once_with(
        "GET", "/comments", body={"block_id": "page-xyz"}
    )


# ── comments_to_dicts ──────────────────────────────────────────────


def test_comments_to_dicts_serialization_roundtrip():
    extractor, _ = make_extractor()
    dt = datetime(2026, 4, 10, 10, 0, 0, tzinfo=timezone.utc)
    comment = NotionComment(
        comment_id="c-1",
        discussion_id="d-1",
        parent_type="page_id",
        parent_id="page-abc",
        created_at=dt,
        created_by="user-123",
        text="Hello there",
        rich_text=[],
    )

    result = extractor.comments_to_dicts([comment])

    assert len(result) == 1
    d = result[0]
    assert d["comment_id"] == "c-1"
    assert d["discussion_id"] == "d-1"
    assert d["parent_type"] == "page_id"
    assert d["parent_id"] == "page-abc"
    assert d["created_at"] == dt.isoformat()
    assert d["created_by"] == "user-123"
    assert d["text"] == "Hello there"


def test_comments_to_dicts_none_created_at_serializes_as_none():
    extractor, _ = make_extractor()
    comment = NotionComment(
        comment_id="c-2",
        discussion_id="d-2",
        parent_type="block_id",
        parent_id="block-abc",
        created_at=None,
    )

    result = extractor.comments_to_dicts([comment])
    assert result[0]["created_at"] is None


# ── _parse_comment ─────────────────────────────────────────────────


def test_parse_comment_handles_missing_fields_gracefully():
    extractor, _ = make_extractor()
    result = extractor._parse_comment({})

    assert result.comment_id == ""
    assert result.discussion_id == ""
    assert result.parent_type == ""
    assert result.parent_id == ""
    assert result.text == ""
    assert result.created_by == ""
    assert result.created_at is None


def test_parse_comment_parses_datetime_correctly():
    extractor, _ = make_extractor()
    raw = make_raw_comment(created_time="2026-04-10T10:00:00.000Z")
    result = extractor._parse_comment(raw)

    assert result.created_at is not None
    assert result.created_at.year == 2026
    assert result.created_at.month == 4
    assert result.created_at.day == 10


def test_parse_comment_concatenates_rich_text_segments():
    extractor, _ = make_extractor()
    raw = {
        "id": "c-1",
        "discussion_id": "d-1",
        "parent": {"type": "page_id", "page_id": "p"},
        "rich_text": [
            {"plain_text": "Hello ", "type": "text"},
            {"plain_text": "world", "type": "text"},
        ],
        "created_by": {"id": "u"},
        "created_time": "2026-01-01T00:00:00.000Z",
    }
    result = extractor._parse_comment(raw)
    assert result.text == "Hello world"
