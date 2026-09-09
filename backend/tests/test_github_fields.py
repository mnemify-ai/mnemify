"""Tests for src.harvester.github.fields flatteners."""

from __future__ import annotations

from src.harvester.github.fields import (
    flatten_discussion_fields,
    flatten_issue_fields,
    flatten_pr_fields,
    flatten_readme_fields,
)


# ── flatten_issue_fields ──────────────────────────────────────────


def test_flatten_issue_basic_shape():
    issue = {
        "number": 42, "title": "Fix bug", "state": "open",
        "user": {"login": "alice"},
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "assignees": [{"login": "bob"}],
        "milestone": {"title": "v1.0"},
        "created_at": "2026-05-01T10:00:00Z",
        "updated_at": "2026-05-13T14:22:00Z",
        "html_url": "https://github.com/x/y/issues/42",
        "body": "describe the bug",
    }
    out = flatten_issue_fields(issue=issue, comments=[{"body": "c1"}, {"body": "c2"}], repo="x/y")
    assert out["document_type"] == "issue"
    assert out["repo"] == "x/y"
    assert out["number"] == 42
    assert out["state"] == "open"
    assert out["author"] == "alice"
    assert out["labels"] == ["bug", "p1"]
    assert out["assignees"] == ["bob"]
    assert out["milestone"] == "v1.0"
    assert out["comment_count"] == 2
    assert out["body_length"] == len("describe the bug")


# ── flatten_pr_fields ─────────────────────────────────────────────


def test_flatten_pr_distinguishes_draft_and_merged():
    pr_draft = {
        "number": 10, "title": "WIP", "state": "open",
        "user": {"login": "alice"},
        "draft": True, "merged": False, "merged_at": None,
        "head": {"ref": "feature/x"}, "base": {"ref": "main"},
        "labels": [], "assignees": [], "requested_reviewers": [],
        "additions": 5, "deletions": 1, "changed_files": 2,
        "html_url": "https://github.com/o/r/pull/10",
        "body": "",
    }
    out = flatten_pr_fields(pr=pr_draft, comments=[], reviews=[], repo="o/r")
    assert out["draft"] is True
    assert out["merged"] is False
    assert out["head_ref"] == "feature/x"
    assert out["base_ref"] == "main"

    pr_merged = dict(pr_draft, draft=False, merged=True, merged_at="2026-05-13T10:00:00Z")
    out2 = flatten_pr_fields(pr=pr_merged, comments=[], reviews=[], repo="o/r")
    assert out2["merged"] is True
    assert out2["merged_at"] == "2026-05-13T10:00:00Z"
    assert out2["draft"] is False


def test_flatten_pr_review_summary_counts_states():
    reviews = [
        {"state": "APPROVED"},
        {"state": "APPROVED"},
        {"state": "CHANGES_REQUESTED"},
        {"state": "COMMENTED"},
    ]
    pr = {"number": 1, "title": "x", "user": {"login": "a"}, "head": {}, "base": {}, "labels": []}
    out = flatten_pr_fields(pr=pr, comments=[], reviews=reviews, repo="o/r")
    assert out["review_summary"] == {"APPROVED": 2, "CHANGES_REQUESTED": 1, "COMMENTED": 1}


# ── flatten_discussion_fields ─────────────────────────────────────


def test_flatten_discussion_is_answered_flag():
    answered = {
        "number": 1, "title": "Q", "body": "q?",
        "category": {"name": "Q&A", "slug": "q-a"},
        "author": {"login": "alice"}, "answer": {"id": "DC_123"},
        "createdAt": "2026-05-01T10:00:00Z", "updatedAt": "2026-05-13T14:00:00Z",
        "url": "https://github.com/o/r/discussions/1",
    }
    out = flatten_discussion_fields(discussion=answered, comments=[{"body": "x"}], repo="o/r")
    assert out["document_type"] == "discussion"
    assert out["is_answered"] is True
    assert out["answer_comment_id"] == "DC_123"
    assert out["category"] == "Q&A"


def test_flatten_discussion_unanswered_flag():
    d = {"number": 2, "title": "?", "body": "", "category": {"name": "Ideas", "slug": "ideas"},
         "author": {"login": "b"}, "answer": None, "createdAt": "...", "updatedAt": "..."}
    out = flatten_discussion_fields(discussion=d, comments=[], repo="o/r")
    assert out["is_answered"] is False
    assert out["answer_comment_id"] is None


# ── flatten_readme_fields ─────────────────────────────────────────


def test_flatten_readme_basic_shape():
    readme = {"path": "README.md", "size": 1234, "url": "https://api.github.com/.../README.md",
              "html_url": "https://github.com/o/r/blob/main/README.md", "sha": "abc"}
    repo_meta = {"default_branch": "main", "updated_at": "2026-05-13T14:00:00Z"}
    out = flatten_readme_fields(readme=readme, repo_meta=repo_meta, repo="o/r")
    assert out["document_type"] == "readme"
    assert out["repo"] == "o/r"
    assert out["default_branch"] == "main"
    assert out["last_repo_update"] == "2026-05-13T14:00:00Z"
    assert out["path"] == "README.md"
