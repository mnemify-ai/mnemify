"""Tests for src.harvester.github.normalizer."""

from __future__ import annotations

import base64
import json

from src.harvester.github.normalizer import github_to_markdown


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ── Issue ─────────────────────────────────────────────────────────


def test_issue_renders_title_body_and_comments_chronologically():
    envelope = {
        "issue": {
            "number": 42, "title": "Fix bug", "state": "open",
            "user": {"login": "alice"}, "body": "describe the bug",
        },
        "comments": [
            {"created_at": "2026-05-12T10:00:00Z", "user": {"login": "bob"}, "body": "first comment"},
            {"created_at": "2026-05-13T11:00:00Z", "user": {"login": "carol"}, "body": "second"},
        ],
    }
    md = github_to_markdown(
        json.dumps(envelope).encode(),
        {"document_type": "issue", "labels": ["bug"], "repo": "o/r"},
    )
    assert "[Issue #42] Fix bug" in md
    assert "**State:** open" in md
    assert "@alice" in md
    assert "## Comments" in md
    # Chronological — bob's heading appears before carol's
    bob_pos = md.index("@bob")
    carol_pos = md.index("@carol")
    assert bob_pos < carol_pos


# ── PR ────────────────────────────────────────────────────────────


def test_pr_renders_reviews_block():
    envelope = {
        "pr": {
            "number": 10, "title": "Refactor x", "state": "closed",
            "user": {"login": "alice"}, "body": "the change",
            "draft": False, "merged": True, "head": {"ref": "feature/x"}, "base": {"ref": "main"},
        },
        "comments": [],
        "reviews": [
            {"state": "APPROVED", "user": {"login": "bob"}, "body": "LGTM", "submitted_at": "2026-05-13T10:00:00Z"},
            {"state": "CHANGES_REQUESTED", "user": {"login": "carol"}, "body": "fix the X", "submitted_at": "2026-05-13T11:00:00Z"},
        ],
    }
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "pr", "repo": "o/r"})
    assert "[PR #10]" in md
    assert "## Reviews" in md
    assert "Approved" in md  # Title-cased
    assert "Changes Requested" in md
    assert "LGTM" in md
    assert "fix the X" in md
    assert "`feature/x` → `main`" in md


def test_pr_draft_shown_in_header():
    envelope = {
        "pr": {"number": 1, "title": "WIP", "state": "open", "draft": True, "merged": False,
               "user": {"login": "alice"}, "body": "", "head": {}, "base": {}},
        "comments": [], "reviews": [],
    }
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "pr"})
    assert "draft" in md.lower()


# ── Discussion ────────────────────────────────────────────────────


def test_discussion_skips_minimized_comments():
    envelope = {
        "discussion": {
            "number": 5, "title": "How do I X?", "body": "asking…",
            "category": {"name": "Q&A", "slug": "q-a"}, "answer": None,
            "author": {"login": "alice"},
            "comments": [
                {"createdAt": "2026-05-12T10:00:00Z", "author": {"login": "bob"},
                 "body": "visible answer", "isMinimized": False, "replies": {"nodes": []}},
                {"createdAt": "2026-05-12T11:00:00Z", "author": {"login": "spam"},
                 "body": "hidden", "isMinimized": True, "replies": {"nodes": []}},
            ],
        },
    }
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "discussion"})
    assert "[Discussion #5]" in md
    assert "visible answer" in md
    assert "hidden" not in md
    assert "unanswered" in md


def test_discussion_answered_status_in_header():
    envelope = {
        "discussion": {"number": 7, "title": "Q", "body": "?",
                       "category": {"name": "Q&A"}, "answer": {"id": "DC_1"},
                       "author": {"login": "alice"}, "comments": []},
    }
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "discussion"})
    assert "answered" in md


# ── README ────────────────────────────────────────────────────────


def test_readme_base64_decodes_and_gets_heading():
    body = "# Project\n\nThis is the project.\n"
    envelope = {
        "readme": {"content": _b64(body), "encoding": "base64"},
        "repo": {"default_branch": "main"},
    }
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "readme", "repo": "o/r"})
    assert md.startswith("# o/r — README")
    assert "This is the project." in md


def test_readme_empty_body_falls_back_to_placeholder():
    envelope = {"readme": {"content": _b64(""), "encoding": "base64"}, "repo": {}}
    md = github_to_markdown(json.dumps(envelope).encode(), {"document_type": "readme", "repo": "o/r"})
    assert "_(empty README)_" in md
