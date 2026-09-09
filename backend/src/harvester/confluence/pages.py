"""PageExtractor — iterate Confluence spaces and fetch full pages.

ATL-11 implementation.  Consumes :class:`ConfluenceClient` (ATL-10) and
yields raw page dicts to callers.  No ``ConfluencePage`` conversion
happens here — that lives in the plugin (ATL-13) where the raw payload
is projected into ``DocRef``/``RawDocument``.

Responsibilities:

- :meth:`list_pages` — flatten across ``space_keys``, paginate via
  ``client.list_pages_in_space``, apply a client-side ``since`` filter
  on ``version.when`` (we always request ``expand=version`` so the
  filter has something to compare against).
- :meth:`get_full_page` — fetch a single page with the full expand
  set the plan doc §3.1 calls for.
- :meth:`list_page_attachments` — return the raw attachment dicts
  from ``client.list_attachments``.
- :meth:`_extract_ancestor_chain` — helper that lifts the ordered
  ``[{id, title}]`` chain out of a page dict, tolerating missing or
  malformed entries.

Attachment *ref* assembly (the ``AttachmentRef`` list the plugin needs)
is deliberately deferred to ATL-30; this module only returns raw dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from .client import ConfluenceClient

logger = logging.getLogger(__name__)


# ── Page-fetch expand set (plan doc §3.1) ─────────────────────────
#
# Kept as a module-level constant so tests can assert the plugin
# doesn't drift from the spec.  Order matters only for equality
# comparisons in tests; the API accepts any order.
_FULL_PAGE_EXPAND: list[str] = [
    "body.storage",
    "ancestors",
    "version",
    "metadata.labels",
    "metadata.properties",
    # ``history`` carries the original author + ``createdDate`` that the
    # plan doc §3.1 requires as ``created_at`` / ``author_id`` /
    # ``author_name``.  Without this expand, only ``version.by`` (the
    # *last* editor) is available — that is not the same identity.
    "history",
]


# ── Internal helpers ──────────────────────────────────────────────


def _parse_version_when(raw: str | None) -> datetime | None:
    """Parse a Confluence ``version.when`` ISO-8601 string into aware UTC.

    Confluence Cloud emits ``"2026-04-18T10:11:12.345Z"``.  Python 3.11
    ``datetime.fromisoformat`` handles the ``Z`` suffix natively.  Naive
    results are coerced to UTC so comparisons with the caller's ``since``
    never cross aware/naive boundaries (which would raise ``TypeError``).
    Unparseable or missing values return ``None``.
    """
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        logger.debug("Unparseable version.when: %r", raw)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalise ``dt`` to a UTC-aware datetime for safe comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PageExtractor:
    """Walk Confluence spaces and yield raw page dicts.

    Construction takes a :class:`ConfluenceClient`; the extractor holds
    no additional state of its own, so multiple concurrent callers can
    share one instance safely (the underlying client's retry harness is
    the only shared resource that matters).
    """

    # Page size for list pagination.  Confluence Cloud's hard ceiling
    # is 100; we stay there to minimise round-trips for large spaces.
    _PAGE_SIZE: int = 100

    def __init__(self, client: ConfluenceClient) -> None:
        self.client = client

    # ── Public API ────────────────────────────────────────────────

    async def list_pages(
        self,
        space_keys: list[str],
        since: datetime | None = None,
    ) -> AsyncIterator[dict]:
        """Yield raw page dicts across every space in ``space_keys``.

        For each space, pages are fetched in batches of ``_PAGE_SIZE``
        via :meth:`ConfluenceClient.list_pages_in_space`.  The loop
        terminates when an API page returns fewer results than the
        requested limit — that is the only reliable signal from the
        normalised envelope the client returns (cf. ``client.py`` where
        bare-list responses are wrapped without a ``_links.next`` key).

        ``since`` is accepted for interface compatibility but ignored.
        ``list_pages_in_space`` has no server-side modified-since filter,
        so the previous client-side drop only ever shrunk the iterator —
        which broke Manage Scope expansion (newly-added spaces' pages
        have old ``version.when`` and would be filtered out before the
        orchestrator's per-doc Layer 1 short-circuit could see them).
        Per-doc dedup now happens upstream.

        Always requests ``expand=version`` so downstream code that reads
        ``version.when`` (DocRef.modified_at) still works.

        Yields:
            Raw page dict as returned by the Atlassian REST API.
        """
        expand = ["version"]

        for space_key in space_keys:
            start = 0
            while True:
                envelope = await self.client.list_pages_in_space(
                    space_key=space_key,
                    expand=expand,
                    start=start,
                    limit=self._PAGE_SIZE,
                )
                results = envelope.get("results", []) if envelope else []
                if not results:
                    break

                for page in results:
                    yield page

                if len(results) < self._PAGE_SIZE:
                    break
                start += len(results)

    async def list_pages_under(self, root_page_id: str) -> AsyncIterator[dict]:
        """Yield the page ``root_page_id`` and every descendant page (BFS).

        This is the page-scoped counterpart to :meth:`list_pages` — used
        when the saved scope names individual pages (``page_ids``) instead
        of whole spaces.  The root is fetched first via ``get_page`` so a
        bad/deleted id fails fast with a :class:`ConfluenceAPIError` the
        caller can log per-root; descendants are walked breadth-first via
        ``client.list_child_pages`` with the same pagination contract as
        the space listing.

        ``expand=version,space`` keeps parity with the list-endpoint shape
        the plugin's ``_doc_ref_from_list_page`` expects (``version.when``
        for DocRef.modified_at, ``space.key`` for metadata).
        """
        expand = ["version", "space"]

        root = await self.client.get_page(str(root_page_id), expand=expand)
        if root:
            yield root

        queue: list[str] = [str(root_page_id)]
        while queue:
            parent_id = queue.pop(0)
            start = 0
            while True:
                envelope = await self.client.list_child_pages(
                    parent_id,
                    expand=expand,
                    start=start,
                    limit=self._PAGE_SIZE,
                )
                results = envelope.get("results", []) if envelope else []
                if not results:
                    break

                for page in results:
                    yield page
                    child_id = page.get("id")
                    if child_id:
                        queue.append(str(child_id))

                if len(results) < self._PAGE_SIZE:
                    break
                start += len(results)

    async def get_full_page(self, page_id: str) -> dict:
        """Fetch one page with the full expand set from plan §3.1.

        Returns the raw dict exactly as the Atlassian client returns it
        — no projection into :class:`ConfluencePage`, no HTML rewrite.
        The plugin (ATL-13) owns the transformation into
        ``DocRef``/``RawDocument``.
        """
        return await self.client.get_page(page_id, expand=_FULL_PAGE_EXPAND)

    async def list_page_attachments(self, page_id: str) -> list[dict]:
        """Return the raw attachment dicts for ``page_id`` (possibly empty).

        Unwraps the ``{"results": [...]}`` envelope returned by
        :meth:`ConfluenceClient.list_attachments`.  If the envelope is
        missing or malformed, an empty list is returned — attachments
        are a nice-to-have, not a blocker for harvesting the page body.
        """
        envelope = await self.client.list_attachments(page_id)
        if not envelope:
            return []
        results = envelope.get("results")
        return list(results) if isinstance(results, list) else []

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_ancestor_chain(page: dict) -> list[dict]:
        """Lift the ordered ancestor chain out of a page dict.

        Confluence emits ancestors root-first, immediate-parent-last.
        Each ancestor carries at least ``id`` and ``title``; anything
        else (``_links``, ``extensions``, …) we drop.  Entries missing
        ``id`` are dropped entirely — without an id the entry has no
        referential value.  Missing ``title`` is tolerated and rendered
        as an empty string so downstream consumers can assume the key
        exists.
        """
        raw_ancestors = page.get("ancestors") or []
        chain: list[dict] = []
        for ancestor in raw_ancestors:
            if not isinstance(ancestor, dict):
                continue
            ancestor_id = ancestor.get("id")
            if ancestor_id is None:
                continue
            chain.append(
                {
                    "id": str(ancestor_id),
                    "title": ancestor.get("title") or "",
                }
            )
        return chain
