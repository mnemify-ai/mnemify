"""GraphQL queries for GitHub Discussions.

GitHub's REST API has no Discussions endpoint — the surface is GraphQL
only. Two queries:

- :data:`DISCUSSIONS_QUERY` — paginated list of discussions in a repo,
  ordered by ``UPDATED_AT_DESC`` so we can break early once we walk
  past the incremental ``since`` cutoff.
- :data:`DISCUSSION_DETAIL_QUERY` — one discussion by number with
  nested ``comments`` (and one level of ``replies`` per comment).

GraphQL has a separate point-based quota from REST (~5000/hour at
default complexity). We cap ``first:`` at 50 for both top-level
nodes and nested comments to keep per-query cost reasonable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DISCUSSIONS_QUERY = """
query Discussions($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(
      first: 50
      after: $cursor
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      nodes {
        id
        number
        title
        url
        body
        bodyText
        createdAt
        updatedAt
        locked
        author { login }
        category { id name slug isAnswerable }
        answer { id }
        comments(first: 0) { totalCount }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
""".strip()


DISCUSSION_DETAIL_QUERY = """
query DiscussionDetail($owner: String!, $name: String!, $number: Int!, $commentsCursor: String) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id
      number
      title
      url
      body
      bodyText
      createdAt
      updatedAt
      locked
      author { login }
      category { name slug }
      answer { id }
      comments(first: 50, after: $commentsCursor) {
        nodes {
          id
          body
          bodyText
          createdAt
          updatedAt
          isMinimized
          minimizedReason
          author { login }
          replies(first: 50) {
            nodes {
              id
              body
              bodyText
              createdAt
              isMinimized
              minimizedReason
              author { login }
            }
          }
        }
        pageInfo { endCursor hasNextPage }
      }
    }
  }
}
""".strip()


def split_repo(repo: str) -> tuple[str, str]:
    """Split ``"owner/repo"`` into ``("owner", "repo")``."""
    parts = repo.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"repo must be 'owner/name', got {repo!r}")
    return parts[0], parts[1]


def build_discussion_list_variables(repo: str, *, cursor: str | None) -> dict[str, Any]:
    """Variables for :data:`DISCUSSIONS_QUERY`. ``since`` is enforced
    client-side by the caller (GraphQL has no server-side filter for
    ``updatedAt`` on the discussions connection).
    """
    owner, name = split_repo(repo)
    return {"owner": owner, "name": name, "cursor": cursor}


def build_discussion_detail_variables(
    repo: str, number: int, *, comments_cursor: str | None = None
) -> dict[str, Any]:
    owner, name = split_repo(repo)
    return {
        "owner": owner,
        "name": name,
        "number": int(number),
        "commentsCursor": comments_cursor,
    }


def parse_iso8601(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp (GitHub uses ``Z`` suffix)."""
    if not value:
        return None
    try:
        # Python 3.11+ accepts ``Z`` directly via fromisoformat.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
