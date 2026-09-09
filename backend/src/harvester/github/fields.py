"""Flatten GitHub raw envelopes into manifest-shaped metadata dicts.

Pure functions, no I/O. The plugin calls these at fetch-time to build
the ``RawDocument.metadata`` dict that gets merged into the manifest's
``documents.metadata`` JSON column.

One flattener per ``document_type``:

- :func:`flatten_issue_fields` → ``document_type="issue"``
- :func:`flatten_pr_fields`    → ``document_type="pr"``
- :func:`flatten_discussion_fields` → ``document_type="discussion"``
- :func:`flatten_readme_fields`     → ``document_type="readme"``
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _login(user: dict | None) -> str | None:
    if not user:
        return None
    return user.get("login")


def _names(items: list[dict] | None, key: str = "login") -> list[str]:
    if not items:
        return []
    return [it.get(key) for it in items if it and it.get(key)]


def _label_names(labels: list[dict] | None) -> list[str]:
    if not labels:
        return []
    return [label.get("name") for label in labels if label and label.get("name")]


# ── Issue ────────────────────────────────────────────────────────


def flatten_issue_fields(
    *,
    issue: dict,
    comments: list[dict],
    repo: str,
) -> dict[str, Any]:
    return {
        "document_type": "issue",
        "repo": repo,
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "author": _login(issue.get("user")),
        "assignees": _names(issue.get("assignees")),
        "labels": _label_names(issue.get("labels")),
        "milestone": (issue.get("milestone") or {}).get("title"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "comment_count": len(comments),
        "url": issue.get("html_url"),
        "locked": bool(issue.get("locked")),
        "body_length": len(issue.get("body") or ""),
    }


# ── Pull request ──────────────────────────────────────────────────


def flatten_pr_fields(
    *,
    pr: dict,
    comments: list[dict],
    reviews: list[dict],
    repo: str,
) -> dict[str, Any]:
    review_states: Counter[str] = Counter()
    for r in reviews:
        state = (r.get("state") or "").upper()
        if state:
            review_states[state] += 1

    head = pr.get("head") or {}
    base = pr.get("base") or {}

    return {
        "document_type": "pr",
        "repo": repo,
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "state_reason": pr.get("state_reason"),
        "author": _login(pr.get("user")),
        "assignees": _names(pr.get("assignees")),
        "labels": _label_names(pr.get("labels")),
        "milestone": (pr.get("milestone") or {}).get("title"),
        "merged": bool(pr.get("merged")),
        "merged_at": pr.get("merged_at"),
        "draft": bool(pr.get("draft")),
        "head_ref": head.get("ref"),
        "base_ref": base.get("ref"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
        "review_summary": dict(review_states),
        "requested_reviewers": _names(pr.get("requested_reviewers")),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "closed_at": pr.get("closed_at"),
        "comment_count": len(comments),
        "url": pr.get("html_url"),
        "locked": bool(pr.get("locked")),
        "body_length": len(pr.get("body") or ""),
    }


# ── Discussion ────────────────────────────────────────────────────


def flatten_discussion_fields(
    *,
    discussion: dict,
    comments: list[dict],
    repo: str,
) -> dict[str, Any]:
    answer = discussion.get("answer") or {}
    return {
        "document_type": "discussion",
        "repo": repo,
        "number": discussion.get("number"),
        "title": discussion.get("title"),
        "category": (discussion.get("category") or {}).get("name"),
        "category_slug": (discussion.get("category") or {}).get("slug"),
        "is_answered": bool(answer.get("id")),
        "answer_comment_id": answer.get("id"),
        "author": _login(discussion.get("author")),
        "created_at": discussion.get("createdAt"),
        "updated_at": discussion.get("updatedAt"),
        "locked": bool(discussion.get("locked")),
        "comment_count": len(comments),
        "url": discussion.get("url"),
        "body_length": len(discussion.get("body") or ""),
    }


# ── README ────────────────────────────────────────────────────────


def flatten_readme_fields(
    *,
    readme: dict,
    repo_meta: dict,
    repo: str,
) -> dict[str, Any]:
    return {
        "document_type": "readme",
        "repo": repo,
        "path": readme.get("path"),
        "default_branch": repo_meta.get("default_branch"),
        "last_repo_update": repo_meta.get("updated_at"),
        "size": readme.get("size"),
        "url": readme.get("html_url") or readme.get("url"),
        "sha": readme.get("sha"),
    }
