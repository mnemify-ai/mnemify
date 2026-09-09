"""ThreadExtractor — iterate Gmail threads via the search query.

Mirrors :class:`src.harvester.jira.issues.IssueExtractor`: a thin adapter
over :class:`GmailClient` that owns pagination, the optional safety cap,
and the fetch-one-thread-by-id call. Higher-level concerns (DocRef
assembly, MIME extraction, normalisation) live in
:class:`GmailHarvesterPlugin`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from .client import GmailClient

logger = logging.getLogger(__name__)


class ThreadExtractor:
    """Walk Gmail threads matching a search query and produce raw thread dicts."""

    def __init__(self, client: GmailClient) -> None:
        self.client = client

    async def list_threads(
        self,
        *,
        query: str,
        max_threads: int | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict]:
        """Yield thread stubs (``{id, snippet, historyId}``) for *query*.

        Stops on absent ``nextPageToken`` (the Gmail pagination contract)
        or once ``max_threads`` results have been yielded — whichever
        comes first. The defensive empty-page break protects against a
        degenerate response that returns ``threads=[]`` with a non-None
        token; otherwise the loop would spin forever.
        """
        page_token: str | None = None
        yielded = 0
        while True:
            page = await self.client.list_threads(
                query, page_token=page_token, max_results=page_size
            )
            threads = page.get("threads") or []
            if not threads:
                return

            for stub in threads:
                yield stub
                yielded += 1
                if max_threads is not None and yielded >= max_threads:
                    return

            page_token = page.get("nextPageToken")
            if not page_token:
                return

    async def get_full_thread(self, thread_id: str) -> dict:
        """Fetch the full payload (every message + headers + bodies) for a thread."""
        return await self.client.get_thread(thread_id, format="full")
