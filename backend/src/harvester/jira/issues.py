"""IssueExtractor — iterate Jira projects via JQL and fetch full issues.

Scaffolded in ATL-03, implemented in ATL-23.  Enumeration is strictly
**JQL-based** (per decisions doc 2026-04-19) — no agile boards, no
sprint walks, no ``board.get_backlog``.  This is the Jira analogue of
:class:`src.harvester.confluence.PageExtractor`.

Responsibilities by task:

- ATL-23 (this module): ``list_issues(project_keys, since)``,
  ``get_full_issue(key)``.
- ATL-31 (Phase 1d): ``list_issue_attachments(issue_key)`` — still a
  stub; attachment refs come from ``fields.attachment[]`` in the
  ``get_full_issue`` response.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime

from src.harvester import AttachmentRef
from .client import JiraClient
from .jql import build_jql

logger = logging.getLogger(__name__)


# Concise field list for the JQL list endpoint.  The goal is to keep
# ``DocRef.metadata`` populated (summary, status, project_key, updated,
# issue_type per plan §3.2) without pulling the full issue payload —
# especially the description, which can be a large ADF blob.  The full
# payload is fetched on demand via :meth:`get_full_issue`.
_LIST_FIELDS: list[str] = [
    "summary",
    "status",
    "project",
    "updated",
    "issuetype",
]


class IssueExtractor:
    """Walk Jira projects via JQL and produce raw issue dicts.

    The extractor is a thin adapter over :class:`JiraClient` — it is
    responsible for:

    1. Building the JQL string via :func:`build_jql`.
    2. Paginating through the ``/rest/api/3/search/jql`` response
       using the Cloud-era ``nextPageToken`` cursor.
    3. Fetching a single issue with the full field list + rendered
       fields expansion via :meth:`JiraClient.get_issue`.

    All higher-level concerns (``DocRef`` assembly, story-points field
    resolution, ADF flattening) live in :class:`JiraHarvesterPlugin`
    (ATL-24).
    """

    def __init__(self, client: JiraClient) -> None:
        self.client = client

    async def list_issues(
        self,
        project_keys: list[str],
        since: datetime | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict]:
        """Yield raw issue dicts across the given projects.

        Builds a JQL clause of the form
        ``project in (KEY1, KEY2, ...) AND updated >= "..." ORDER BY updated DESC``
        (or the single-project form when ``len(project_keys) == 1``)
        via :func:`build_jql`, then paginates through the results using
        the ``nextPageToken`` cursor from the
        ``/rest/api/3/search/jql`` response.

        The yielded dicts contain only the fields enumerated in
        :data:`_LIST_FIELDS` — enough to populate ``DocRef.metadata``
        per plan §3.2 without a second fetch.  Call
        :meth:`get_full_issue` on each key for the full payload.

        Termination is guarded two ways:

        - ``nextPageToken`` is absent from the response — the standard
          Atlassian Cloud enhanced-JQL pagination contract.
        - The response has no ``issues`` — defensive break so a
          degenerate page (empty issues + non-None token) cannot spin
          the loop forever.

        Args:
            project_keys: Non-empty list of Jira project keys.
            since: Optional ``updated >= ...`` filter anchor; naive
                datetimes are assumed UTC.
            page_size: Number of issues to request per page; the Jira
                Cloud maximum is 100.

        Yields:
            Raw issue dicts in the REST shape returned by Atlassian.

        Raises:
            ValueError: If ``project_keys`` is empty or contains an
                invalid key (propagated from :func:`build_jql`).
        """
        jql = build_jql(project_keys, since=since)
        next_page_token: str | None = None
        while True:
            page = await self.client.jql_search(
                jql,
                fields=_LIST_FIELDS,
                next_page_token=next_page_token,
                max_results=page_size,
            )
            issues = page.get("issues") or []
            if not issues:
                return

            for issue in issues:
                yield issue

            next_page_token = page.get("nextPageToken")
            if not next_page_token:
                return

    async def get_full_issue(self, issue_key: str) -> dict:
        """Fetch a single issue with the full field set and rendered HTML.

        Passes ``fields=['*all']`` so Atlassian returns every custom
        field (the plugin needs the story-points field, whose id is not
        known until after :func:`discover_story_points_field` runs — see
        ATL-40), and ``expand=['renderedFields']`` so the response
        carries an HTML rendering alongside the ADF body (used by the
        compiler, not the harvester, but cheap to include).

        The returned dict is the raw REST payload — attachments live
        under ``fields.attachment``, ready for ATL-31.

        Args:
            issue_key: The Jira issue key (e.g. ``"CONN-123"``).

        Returns:
            The full ``/rest/api/3/issue/{key}`` response dict.
        """
        return await self.client.get_issue(
            issue_key,
            fields=["*all"],
            expand=["renderedFields"],
        )

    async def list_issue_attachments(self, issue_key: str) -> list[AttachmentRef]:
        """Return :class:`AttachmentRef` list for an issue's attachments.

        Consumes ``fields.attachment[]`` from the issue JSON; each
        ``AttachmentRef.url`` is the absolute ``content`` URL so the
        plugin's ``fetch_attachment`` can stream it via the
        authenticated :class:`JiraClient`.

        Implementation: ATL-31 (Phase 1d — Attachments).
        """
        raise NotImplementedError("ATL-31: IssueExtractor.list_issue_attachments")
