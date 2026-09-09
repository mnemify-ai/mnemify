"""Unit tests for :mod:`src.harvester.jira.fields` (ATL-22, ATL-40).

Covers the two functions that live in ``jira/fields.py``:

- :func:`discover_story_points_field` — auto-discovery of the Jira site's
  Story-points custom field id via ``/rest/api/3/field``.  Preference is
  by name (modern "Story point estimate" beats legacy "Story Points"),
  not by iteration order.  Returns ``None`` when neither name is present.

- :func:`flatten_issue_fields` — projects a raw Jira REST issue JSON into
  the flat metadata dict shape required by :class:`RawDocument.metadata`
  per plan doc §3.2.  Non-lossy: does not emit the description or any
  ADF — the raw JSON is persisted separately by the plugin.

All tests are pure-Python with stubbed :class:`JiraClient`; no network
calls and no fixtures on disk.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.harvester.jira.fields import (
    discover_story_points_field,
    flatten_issue_fields,
)


# ── Helpers ──────────────────────────────────────────────────────


class _StubJiraClient:
    """Minimal stub exposing only :meth:`list_fields`.

    We don't use :class:`unittest.mock.MagicMock` here because
    ``list_fields`` must be an ``async`` callable and coroutines from
    raw MagicMock add friction (need ``AsyncMock``).  A hand-rolled
    stub is simpler and records the call count for the
    "no caching inside the function" invariant.
    """

    def __init__(self, fields: list[dict[str, Any]]) -> None:
        self._fields = fields
        self.list_fields_calls = 0

    async def list_fields(self) -> list[dict[str, Any]]:
        self.list_fields_calls += 1
        return self._fields


def _issue(
    key: str = "CONN-1",
    *,
    fields: dict | None = None,
    self_url: str | None = "https://acme.atlassian.net/rest/api/3/issue/10001",
    links_html: str | None = None,
) -> dict:
    """Build a minimal Jira issue dict for flatten tests.

    Only the top-level ``key``, ``self``, ``_links``, and ``fields`` keys
    are emitted — callers override per-test via the ``fields`` kwarg.
    """
    raw: dict[str, Any] = {"key": key, "fields": fields or {}}
    if self_url is not None:
        raw["self"] = self_url
    if links_html is not None:
        raw["_links"] = {"html": links_html}
    return raw


# ─────────────────────────────────────────────────────────────────
#  ATL-40 — discover_story_points_field
# ─────────────────────────────────────────────────────────────────


async def test_discover_modern_cloud_story_point_estimate():
    """Modern Jira Cloud exposes "Story point estimate" — returns its id."""
    fields = [
        {"id": "summary", "name": "Summary"},
        {"id": "customfield_10026", "name": "Story point estimate"},
        {"id": "customfield_10040", "name": "Sprint"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10026"
    assert client.list_fields_calls == 1


async def test_discover_legacy_story_points():
    """Legacy site only has "Story Points" — returns it."""
    fields = [
        {"id": "summary", "name": "Summary"},
        {"id": "customfield_10016", "name": "Story Points"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10016"


async def test_discover_renamed_custom_field_id():
    """Renamed custom field — "Story Points" lives at non-default id."""
    fields = [
        {"id": "customfield_10099", "name": "Story Points"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10099"


async def test_discover_prefers_modern_name_over_iteration_order():
    """Both names present, legacy listed first — modern still wins.

    This is the key invariant of the preference-order logic: the function
    must pick "Story point estimate" even when "Story Points" appears
    earlier in the field listing.
    """
    fields = [
        {"id": "customfield_10016", "name": "Story Points"},
        {"id": "customfield_10026", "name": "Story point estimate"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10026"


async def test_discover_case_insensitive_match():
    """Match is case-insensitive on the display name."""
    fields = [
        {"id": "customfield_10026", "name": "STORY POINT ESTIMATE"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10026"


async def test_discover_returns_none_when_absent():
    """Neither canonical name present — returns ``None``."""
    fields = [
        {"id": "summary", "name": "Summary"},
        {"id": "customfield_10010", "name": "Epic Link"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result is None


async def test_discover_returns_none_on_empty_field_list():
    """Empty field list (permissions issue, weird install) — ``None``."""
    client = _StubJiraClient([])

    result = await discover_story_points_field(client)

    assert result is None


async def test_discover_skips_malformed_entries():
    """Fields without ``id`` or ``name`` are silently skipped."""
    fields = [
        {"name": "Story point estimate"},                 # missing id
        {"id": "customfield_10099"},                      # missing name
        {"id": "customfield_10026", "name": "Story Points"},
    ]
    client = _StubJiraClient(fields)

    result = await discover_story_points_field(client)

    assert result == "customfield_10026"


async def test_discover_no_caching_inside_function():
    """Each call re-fetches — caching is the plugin's responsibility (ATL-41)."""
    fields = [{"id": "customfield_10026", "name": "Story point estimate"}]
    client = _StubJiraClient(fields)

    await discover_story_points_field(client)
    await discover_story_points_field(client)
    await discover_story_points_field(client)

    assert client.list_fields_calls == 3


# ─────────────────────────────────────────────────────────────────
#  ATL-22 — flatten_issue_fields
# ─────────────────────────────────────────────────────────────────


def test_flatten_story_with_points():
    """Story issue with assignee, reporter, labels, and story points."""
    issue = _issue(
        key="CONN-100",
        fields={
            "project": {"key": "CONN", "name": "Mnemify"},
            "issuetype": {"name": "Story"},
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "assignee": {"accountId": "u1", "displayName": "Alice"},
            "reporter": {"accountId": "u2", "displayName": "Bob"},
            "created": "2026-04-10T10:00:00.000+0000",
            "updated": "2026-04-15T11:00:00.000+0000",
            "labels": ["backend", "api"],
            "customfield_10026": 5.0,
            "attachment": [],
        },
    )

    meta = flatten_issue_fields(issue, story_points_field="customfield_10026")

    assert meta == {
        "document_type": "issue",
        "url": "https://acme.atlassian.net/browse/CONN-100",
        "project_key": "CONN",
        "issue_type": "Story",
        "status": "In Progress",
        "priority": "High",
        "assignee_id": "u1",
        "assignee_name": "Alice",
        "reporter_id": "u2",
        "reporter_name": "Bob",
        "created": "2026-04-10T10:00:00.000+0000",
        "updated": "2026-04-15T11:00:00.000+0000",
        "labels": ["backend", "api"],
        "story_points": 5.0,
        "resolved_story_points_field": "customfield_10026",
        "attachment_count": 0,
    }


def test_flatten_bug_with_attachments_and_no_priority():
    """Bug issue, has attachments, priority explicitly null."""
    issue = _issue(
        key="CONN-42",
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Bug"},
            "status": {"name": "Open"},
            "priority": None,                               # explicit null
            "assignee": {"accountId": "u9", "displayName": "Chris"},
            "reporter": {"accountId": "u2", "displayName": "Bob"},
            "created": "2026-04-01T08:00:00.000+0000",
            "updated": "2026-04-02T09:00:00.000+0000",
            "labels": [],
            "attachment": [
                {"id": "1", "filename": "log.txt"},
                {"id": "2", "filename": "screenshot.png"},
                {"id": "3", "filename": "trace.json"},
            ],
        },
    )

    meta = flatten_issue_fields(issue, story_points_field="customfield_10026")

    assert meta["issue_type"] == "Bug"
    assert meta["priority"] is None
    assert meta["attachment_count"] == 3
    assert meta["story_points"] is None                     # no custom field on issue
    assert meta["resolved_story_points_field"] == "customfield_10026"


def test_flatten_epic_no_assignee():
    """Epic with ``assignee = null`` (unassigned) — both id and name are None."""
    issue = _issue(
        key="CONN-7",
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Epic"},
            "status": {"name": "To Do"},
            "priority": {"name": "Medium"},
            "assignee": None,                               # unassigned
            "reporter": {"accountId": "u2", "displayName": "Bob"},
            "created": "2026-03-01T00:00:00.000+0000",
            "updated": "2026-03-01T00:00:00.000+0000",
            "labels": ["epic"],
            "attachment": [],
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["assignee_id"] is None
    assert meta["assignee_name"] is None
    assert meta["reporter_id"] == "u2"
    assert meta["reporter_name"] == "Bob"
    assert meta["issue_type"] == "Epic"


def test_flatten_subtask_with_missing_fields():
    """Sub-task with most optional fields missing entirely (not null)."""
    issue = _issue(
        key="CONN-999",
        fields={
            # intentionally minimal — only fields that must be present
            "project": {"key": "CONN"},
            "issuetype": {"name": "Sub-task"},
            "status": {"name": "Done"},
            # no priority, no assignee, no reporter, no labels, no attachments
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["issue_type"] == "Sub-task"
    assert meta["priority"] is None
    assert meta["assignee_id"] is None
    assert meta["assignee_name"] is None
    assert meta["reporter_id"] is None
    assert meta["reporter_name"] is None
    assert meta["labels"] == []
    assert meta["attachment_count"] == 0
    assert meta["story_points"] is None
    assert meta["resolved_story_points_field"] is None


def test_flatten_story_points_field_none_means_no_lookup():
    """``story_points_field=None`` — never attempt a customfield lookup."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Story"},
            "status": {"name": "Open"},
            # Even if the issue has a value under the legacy id, we must
            # not read it — auto-discovery found nothing, so points are
            # definitively unknown on this site.
            "customfield_10016": 8,
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["story_points"] is None
    assert meta["resolved_story_points_field"] is None


def test_flatten_story_points_integer_coerced_to_float():
    """Integer-valued points are coerced to float (Jira emits floats)."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Story"},
            "status": {"name": "Open"},
            "customfield_10026": 3,                         # integer
        },
    )

    meta = flatten_issue_fields(issue, story_points_field="customfield_10026")

    assert meta["story_points"] == 3.0
    assert isinstance(meta["story_points"], float)


def test_flatten_story_points_string_numeric_coerced():
    """Some custom configs store points as strings — coerce when numeric."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Story"},
            "status": {"name": "Open"},
            "customfield_10026": "8",
        },
    )

    meta = flatten_issue_fields(issue, story_points_field="customfield_10026")

    assert meta["story_points"] == 8.0


def test_flatten_story_points_unparseable_string_is_none():
    """Non-numeric string under the custom field — points become ``None``."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Story"},
            "status": {"name": "Open"},
            "customfield_10026": "N/A",
        },
    )

    meta = flatten_issue_fields(issue, story_points_field="customfield_10026")

    assert meta["story_points"] is None


# ── URL resolution ────────────────────────────────────────────────


def test_flatten_url_prefers_links_html_when_present():
    """``_links.html`` wins over derivation from ``self``."""
    issue = _issue(
        key="CONN-1",
        self_url="https://acme.atlassian.net/rest/api/3/issue/10001",
        links_html="https://acme.atlassian.net/browse/CONN-1",
        fields={"project": {"key": "CONN"}, "issuetype": {"name": "Task"}, "status": {"name": "Open"}},
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["url"] == "https://acme.atlassian.net/browse/CONN-1"


def test_flatten_url_derived_from_self_when_no_links():
    """``self`` is stripped at ``/rest/api/`` and ``/browse/{key}`` appended."""
    issue = _issue(
        key="CONN-42",
        self_url="https://acme.atlassian.net/rest/api/3/issue/10042",
        fields={"project": {"key": "CONN"}, "issuetype": {"name": "Task"}, "status": {"name": "Open"}},
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["url"] == "https://acme.atlassian.net/browse/CONN-42"


def test_flatten_url_empty_when_neither_self_nor_links():
    """No ``self``, no ``_links`` — URL falls back to empty string."""
    issue = _issue(
        key="CONN-5",
        self_url=None,
        fields={"project": {"key": "CONN"}, "issuetype": {"name": "Task"}, "status": {"name": "Open"}},
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["url"] == ""


# ── project_key resolution ────────────────────────────────────────


def test_flatten_project_key_from_project_object():
    """Primary path: ``fields.project.key``."""
    issue = _issue(
        key="PLAT-10",
        fields={
            "project": {"key": "PLAT", "name": "Platform"},
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["project_key"] == "PLAT"


def test_flatten_project_key_fallback_from_issue_key():
    """Fallback: split the issue key on the final ``-``.

    Some abbreviated list responses omit ``fields.project``; the issue
    key prefix is globally-unique-per-instance by construction so it
    is a safe fallback.
    """
    issue = _issue(
        key="OPS-123",
        fields={
            # project intentionally absent
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta["project_key"] == "OPS"


# ── Parametrised shape assertions ─────────────────────────────────


@pytest.mark.parametrize(
    "key,metadata_key,expected",
    [
        # Required keys — assert they always exist in the output dict,
        # independent of issue shape.
        ("doc_type",           "document_type", "issue"),
        ("resolved_sp_empty",  "resolved_story_points_field", None),
    ],
)
def test_flatten_constant_output_keys(key, metadata_key, expected):
    """A minimal issue still produces the constant metadata keys."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert meta[metadata_key] == expected


REQUIRED_METADATA_KEYS = {
    "document_type",
    "url",
    "project_key",
    "issue_type",
    "status",
    "priority",
    "assignee_id",
    "assignee_name",
    "reporter_id",
    "reporter_name",
    "created",
    "updated",
    "labels",
    "story_points",
    "resolved_story_points_field",
    "attachment_count",
}


def test_flatten_emits_all_required_metadata_keys():
    """Every key from plan §3.2 must be present in the output dict."""
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert set(meta.keys()) == REQUIRED_METADATA_KEYS


def test_flatten_is_non_lossy_no_description_emitted():
    """Non-lossy projection — description ADF is NOT emitted.

    The raw JSON (including ADF) is the caller's responsibility to
    persist via ``RawDocument.content``.  This function only emits
    metadata for filter / manifest / compiler consumption.
    """
    issue = _issue(
        fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Story"},
            "status": {"name": "Open"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Important"}]}],
            },
            "summary": "A story",
        },
    )

    meta = flatten_issue_fields(issue, story_points_field=None)

    assert "description" not in meta
    assert "summary" not in meta
    assert "raw_json" not in meta


def test_flatten_labels_always_returns_list():
    """``labels`` is always a list — never ``None``."""
    # Case 1: key missing
    meta1 = flatten_issue_fields(
        _issue(fields={"project": {"key": "CONN"}, "issuetype": {"name": "Task"}, "status": {"name": "Open"}}),
        story_points_field=None,
    )
    assert meta1["labels"] == []

    # Case 2: key present but null
    meta2 = flatten_issue_fields(
        _issue(fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
            "labels": None,
        }),
        story_points_field=None,
    )
    assert meta2["labels"] == []

    # Case 3: populated
    meta3 = flatten_issue_fields(
        _issue(fields={
            "project": {"key": "CONN"},
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
            "labels": ["a", "b"],
        }),
        story_points_field=None,
    )
    assert meta3["labels"] == ["a", "b"]
