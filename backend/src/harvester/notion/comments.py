"""Comment extraction from Notion pages.

Harvests open (un-resolved) comments from pages, including inline
discussion threads on specific blocks.

Endpoint: GET /comments?block_id={page_id_or_block_id}
Pagination: cursor-based (same as other Notion endpoints)
"""
from __future__ import annotations

import logging
from datetime import datetime

from .client import NotionClient
from .models import NotionComment

logger = logging.getLogger(__name__)


class CommentExtractor:
    """Extracts comments from Notion pages."""

    def __init__(self, client: NotionClient):
        self.client = client

    async def get_page_comments(self, page_id: str) -> list[NotionComment]:
        """Fetch all open comments for a page."""
        raw_results = await self.client.paginate("GET", "/comments", body={"block_id": page_id})
        comments = [self._parse_comment(raw) for raw in raw_results]
        logger.info(f"Found {len(comments)} comments on page {page_id[:8]}...")
        return comments

    def comments_to_dicts(self, comments: list[NotionComment]) -> list[dict]:
        return [
            {
                "comment_id": c.comment_id,
                "discussion_id": c.discussion_id,
                "parent_type": c.parent_type,
                "parent_id": c.parent_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "created_by": c.created_by,
                "text": c.text,
            }
            for c in comments
        ]

    def _parse_comment(self, raw: dict) -> NotionComment:
        parent = raw.get("parent", {})
        parent_type = parent.get("type", "")
        parent_id = parent.get(parent_type, "")
        rich_text = raw.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_text)
        created_by_obj = raw.get("created_by", {})
        created_by = created_by_obj.get("id", "")
        return NotionComment(
            comment_id=raw.get("id", ""),
            discussion_id=raw.get("discussion_id", ""),
            parent_type=parent_type,
            parent_id=parent_id,
            created_at=self._parse_dt(raw.get("created_time")),
            created_by=created_by,
            text=text,
            rich_text=rich_text,
        )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
