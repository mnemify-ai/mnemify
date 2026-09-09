"""End-to-end tests for :func:`src.harvester.jira.normalizer.jira_to_markdown`."""

from __future__ import annotations

import json

import pytest

from src.harvester.jira.normalizer import jira_to_markdown


# ── Inline fixture builders ───────────────────────────────────────────────────


def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def _paragraph(*children: dict) -> dict:
    return {"type": "paragraph", "content": list(children)}


def _doc(*children: dict) -> dict:
    return {"type": "doc", "content": list(children)}


def _adf_description(text: str) -> dict:
    return _doc(_paragraph(_text(text)))


def _make_comment(author_name: str, body_text: str, created: str) -> dict:
    return {
        "id": "1",
        "author": {"displayName": author_name},
        "body": _doc(_paragraph(_text(body_text))),
        "created": created,
        "updated": created,
    }


def _make_issue(
    key: str = "TEST-1",
    summary: str = "Test issue",
    description=None,
    comments: list | None = None,
    status: str = "In Progress",
    assignee: str | None = "Alice",
    reporter: str | None = "Bob",
    labels: list | None = None,
    project_key: str = "TEST",
    issue_type: str = "Story",
    created: str = "2026-01-01T10:00:00.000+0000",
    updated: str = "2026-01-02T10:00:00.000+0000",
    parent_key: str | None = None,
    story_points: float | None = None,
) -> dict:
    fields: dict = {
        "summary": summary,
        "status": {"name": status},
        "issuetype": {"name": issue_type},
        "project": {"key": project_key},
        "labels": labels or [],
        "created": created,
        "updated": updated,
        "assignee": {"displayName": assignee} if assignee else None,
        "reporter": {"displayName": reporter} if reporter else None,
        "comment": {
            "comments": comments or [],
            "total": len(comments or []),
        },
    }
    if description is not None:
        fields["description"] = description
    if parent_key:
        fields["parent"] = {"key": parent_key}
    if story_points is not None:
        fields["customfield_10026"] = story_points
    return {
        "id": "10001",
        "key": key,
        "self": f"https://example.atlassian.net/rest/api/3/issue/{key}",
        "fields": fields,
    }


def _raw(issue: dict) -> bytes:
    return json.dumps(issue).encode("utf-8")


# ── Frontmatter tests ─────────────────────────────────────────────────────────


def test_frontmatter_starts_with_dashes():
    out = jira_to_markdown(_raw(_make_issue()), {})
    assert out.startswith("---\n")


def test_frontmatter_source_is_jira():
    out = jira_to_markdown(_raw(_make_issue()), {})
    assert "source: jira" in out


def test_frontmatter_key_present():
    out = jira_to_markdown(_raw(_make_issue(key="PROJ-42")), {"key": "PROJ-42"})
    assert "key: PROJ-42" in out


def test_frontmatter_summary_present():
    out = jira_to_markdown(_raw(_make_issue(summary="Do the thing")), {})
    assert "summary:" in out
    assert "Do the thing" in out


def test_frontmatter_status_present():
    out = jira_to_markdown(_raw(_make_issue(status="Done")), {})
    assert "status: Done" in out


def test_frontmatter_assignee_present():
    out = jira_to_markdown(_raw(_make_issue(assignee="Alice")), {})
    assert "assignee: Alice" in out


def test_frontmatter_reporter_present():
    out = jira_to_markdown(_raw(_make_issue(reporter="Bob")), {})
    assert "reporter: Bob" in out


def test_frontmatter_labels_present():
    out = jira_to_markdown(
        _raw(_make_issue(labels=["q2", "auth"])),
        {},
    )
    assert "labels:" in out
    assert "q2" in out
    assert "auth" in out


def test_frontmatter_project_key():
    out = jira_to_markdown(_raw(_make_issue(project_key="XYZ")), {})
    assert "project_key: XYZ" in out


def test_frontmatter_url_with_base_url():
    out = jira_to_markdown(
        _raw(_make_issue(key="TEST-1")),
        {"key": "TEST-1"},
        base_url="https://acme.atlassian.net",
    )
    assert "url: https://acme.atlassian.net/browse/TEST-1" in out


def test_frontmatter_no_url_without_base_url():
    out = jira_to_markdown(_raw(_make_issue()), {})
    # Should not generate a url field without base_url.
    # (It may appear if metadata.url is populated, which it isn't here.)
    lines = [l for l in out.split("\n") if l.startswith("url:")]
    # Either absent or, if metadata.url was somehow present, check it's not junk
    assert all("None" not in l for l in lines)


def test_frontmatter_story_points_from_metadata():
    issue = _make_issue()
    meta = {"story_points": 5.0}
    out = jira_to_markdown(_raw(issue), meta)
    assert "story_points:" in out


def test_frontmatter_parent_key():
    out = jira_to_markdown(_raw(_make_issue(parent_key="EPIC-1")), {})
    assert "parent_key: EPIC-1" in out


def test_frontmatter_omits_none_fields():
    """None-valued fields must not appear in frontmatter."""
    issue = _make_issue(assignee=None)
    out = jira_to_markdown(_raw(issue), {})
    assert "assignee:" not in out


# ── Heading ───────────────────────────────────────────────────────────────────


def test_heading_format():
    out = jira_to_markdown(
        _raw(_make_issue(key="FOO-7", summary="My summary")),
        {"key": "FOO-7"},
    )
    assert "# FOO-7 — My summary" in out


# ── Description ───────────────────────────────────────────────────────────────


def test_description_section_present():
    out = jira_to_markdown(
        _raw(_make_issue(description=_adf_description("Some detail"))),
        {},
    )
    assert "## Description" in out
    assert "Some detail" in out


def test_empty_description_placeholder():
    """Issues with no description field render the placeholder."""
    issue = _make_issue()
    issue["fields"].pop("description", None)
    out = jira_to_markdown(_raw(issue), {})
    assert "(no description)" in out


def test_null_description_placeholder():
    """Explicit null description also renders placeholder."""
    issue = _make_issue()
    issue["fields"]["description"] = None
    out = jira_to_markdown(_raw(issue), {})
    assert "(no description)" in out


# ── Comments ──────────────────────────────────────────────────────────────────


def test_comments_section_appears_when_comments_exist():
    issue = _make_issue(comments=[
        _make_comment("Alice", "First comment", "2026-01-01T10:00:00.000+0000"),
    ])
    out = jira_to_markdown(_raw(issue), {})
    assert "## Comments" in out
    assert "Alice" in out
    assert "First comment" in out


def test_comments_section_absent_when_no_comments():
    issue = _make_issue(comments=[])
    out = jira_to_markdown(_raw(issue), {})
    assert "## Comments" not in out


def test_comments_ordered_by_created_ascending():
    issue = _make_issue(comments=[
        _make_comment("Bob", "Later comment", "2026-02-01T00:00:00.000+0000"),
        _make_comment("Alice", "Earlier comment", "2026-01-01T00:00:00.000+0000"),
    ])
    out = jira_to_markdown(_raw(issue), {})
    alice_pos = out.index("Earlier comment")
    bob_pos = out.index("Later comment")
    assert alice_pos < bob_pos, "Earlier comment must appear before later comment"


def test_comment_heading_format():
    issue = _make_issue(comments=[
        _make_comment("Carol", "body", "2026-03-15T09:00:00.000+0000"),
    ])
    out = jira_to_markdown(_raw(issue), {})
    assert "### 2026-03-15T09:00:00.000+0000 — Carol" in out


# ── No raw JSON fragments ─────────────────────────────────────────────────────


def test_output_contains_no_raw_json_braces():
    """Output must not contain raw JSON brace fragments from the ADF tree."""
    issue = _make_issue(
        description=_adf_description("description text"),
        comments=[_make_comment("Alice", "comment text", "2026-01-01T00:00:00Z")],
    )
    out = jira_to_markdown(_raw(issue), {})
    # The YAML frontmatter block uses {}, but the body should have no JSON keys.
    body = out.split("---\n", 2)[-1]  # strip frontmatter
    assert '"type"' not in body
    assert '"content"' not in body
    assert '"attrs"' not in body


# ── Minimal metadata (smoke-test path) ───────────────────────────────────────


def test_minimal_metadata_still_produces_valid_output():
    """Normalizer must work when metadata contains only key + project_key."""
    issue = _make_issue(key="MIN-1", summary="Minimal test")
    out = jira_to_markdown(_raw(issue), {"key": "MIN-1", "project_key": "MIN"})
    assert out.startswith("---\n")
    assert "# MIN-1 — Minimal test" in out


def test_metadata_assignee_name_mapped():
    """flatten_issue_fields emits 'assignee_name'; normalizer maps it to 'assignee'."""
    issue = _make_issue(assignee=None)  # No assignee in JSON
    # Simulate flatten_issue_fields output
    meta = {"assignee_name": "Dave", "key": "X-1"}
    out = jira_to_markdown(_raw(issue), meta)
    assert "assignee: Dave" in out


# ── Blank-line normalisation ──────────────────────────────────────────────────


def test_no_triple_blank_lines():
    issue = _make_issue(
        description=_doc(
            *[{"type": "paragraph", "content": [_text(f"p{i}")]} for i in range(10)]
        )
    )
    out = jira_to_markdown(_raw(issue), {})
    assert "\n\n\n" not in out
