"""Per-repo extractor — paginated walks across issues, PRs, discussions, READMEs.

Mirrors :mod:`src.harvester.jira.issues` in shape: a class that
holds the :class:`GitHubClient` and exposes async iterators / coroutines
the plugin assembles into ``DocRef`` / ``RawDocument`` envelopes.

Key incremental contracts:

- Issues + PRs share ``GET /repos/{r}/issues`` (PRs have a
  ``pull_request`` field). The endpoint accepts ``since=<iso>`` so
  incremental sync is server-side.
- Discussions are GraphQL-only and the connection has no ``since``
  filter — we paginate ``UPDATED_AT_DESC`` and stop when items go
  below the cutoff.
- READMEs use repo-level ``updated_at`` as the freshness signal —
  cheap, slightly over-refetches; the orchestrator's content-hash
  gate (``orchestrator.py:380``) suppresses redundant writes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from .client import GitHubAPIError, GitHubClient
from .gql import (
    DISCUSSION_DETAIL_QUERY,
    DISCUSSIONS_QUERY,
    build_discussion_detail_variables,
    build_discussion_list_variables,
    parse_iso8601,
)

logger = logging.getLogger(__name__)


class RepoExtractor:
    """Per-repo extractors. Holds a :class:`GitHubClient`; stateless otherwise."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    # ── Issues + PRs (one endpoint, two document_types) ───────────

    async def list_issues_and_prs(
        self,
        repo: str,
        *,
        since: datetime | None,
    ) -> AsyncIterator[dict]:
        """Yield list-view issue/PR dicts. ``pull_request`` field present → PR."""
        params: dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
        }
        if since is not None:
            params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        url: str | None = f"/repos/{repo}/issues"
        while url:
            body, next_url = await self._client.get_with_link(
                url, params=params if url == f"/repos/{repo}/issues" else None,
            )
            if isinstance(body, list):
                for item in body:
                    yield item
            url = next_url

    async def get_full_issue(self, repo: str, number: int) -> dict[str, Any]:
        issue = await self._client.get(f"/repos/{repo}/issues/{number}")
        comments = await self._collect_issue_comments(repo, number)
        return {"issue": issue, "comments": comments}

    async def get_full_pr(self, repo: str, number: int) -> dict[str, Any]:
        pr = await self._client.get(f"/repos/{repo}/pulls/{number}")
        comments = await self._collect_issue_comments(repo, number)
        reviews = await self._collect_pr_reviews(repo, number)
        return {"pr": pr, "comments": comments, "reviews": reviews}

    async def _collect_issue_comments(self, repo: str, number: int) -> list[dict]:
        out: list[dict] = []
        url: str | None = f"/repos/{repo}/issues/{number}/comments"
        params: dict[str, Any] | None = {"per_page": 100}
        while url:
            body, next_url = await self._client.get_with_link(url, params=params)
            params = None  # only the first page carries query params
            if isinstance(body, list):
                out.extend(body)
            url = next_url
        return out

    async def _collect_pr_reviews(self, repo: str, number: int) -> list[dict]:
        out: list[dict] = []
        url: str | None = f"/repos/{repo}/pulls/{number}/reviews"
        params: dict[str, Any] | None = {"per_page": 100}
        while url:
            body, next_url = await self._client.get_with_link(url, params=params)
            params = None
            if isinstance(body, list):
                out.extend(body)
            url = next_url
        return out

    # ── Discussions (GraphQL) ────────────────────────────────────

    async def list_discussions(
        self,
        repo: str,
        *,
        since: datetime | None,
    ) -> AsyncIterator[dict]:
        """Yield discussion list nodes; stop early when ``updatedAt < since``.

        Raises :class:`GitHubAPIError` only on hard failures — auth /
        scope errors surface to the plugin so it can log a hint and
        continue with the other entity types.
        """
        cursor: str | None = None
        while True:
            data = await self._client.graphql(
                DISCUSSIONS_QUERY,
                build_discussion_list_variables(repo, cursor=cursor),
            )
            connection = ((data.get("repository") or {}).get("discussions") or {})
            nodes = connection.get("nodes") or []
            for node in nodes:
                if since is not None:
                    updated = parse_iso8601(node.get("updatedAt"))
                    if updated is not None and updated <= since:
                        # Sorted DESC — once we cross the cutoff, we're done.
                        return
                yield node
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return
            cursor = page_info.get("endCursor")
            if not cursor:
                return

    async def get_full_discussion(self, repo: str, number: int) -> dict[str, Any]:
        """Fetch one discussion with all comments + replies (paginated)."""
        all_comments: list[dict] = []
        cursor: str | None = None
        discussion: dict[str, Any] = {}
        while True:
            data = await self._client.graphql(
                DISCUSSION_DETAIL_QUERY,
                build_discussion_detail_variables(repo, number, comments_cursor=cursor),
            )
            disc = (data.get("repository") or {}).get("discussion") or {}
            if not discussion:
                # Snapshot all non-comments fields once.
                discussion = {k: v for k, v in disc.items() if k != "comments"}
            comments_conn = disc.get("comments") or {}
            all_comments.extend(comments_conn.get("nodes") or [])
            page_info = comments_conn.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        discussion["comments"] = all_comments
        return {"discussion": discussion}

    # ── READMEs ──────────────────────────────────────────────────

    async def get_repo(self, repo: str) -> dict[str, Any]:
        return await self._client.get(f"/repos/{repo}")  # type: ignore[return-value]

    async def get_readme_doc(self, repo: str) -> dict[str, Any] | None:
        """Return ``{"readme": …, "repo": …}`` or ``None`` when no README.

        Repo-level ``updated_at`` is the freshness signal — cheap.
        Per-file commit-history lookup for true README accuracy is
        deferred to V1.1.
        """
        try:
            readme = await self._client.get(f"/repos/{repo}/readme")
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        repo_meta = await self.get_repo(repo)
        return {"readme": readme, "repo": repo_meta}
