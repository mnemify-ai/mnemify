"""Tests for :class:`JiraHarvesterPlugin` (ATL-24 + ATL-41).

Covers:
  1. Scaffold-era invariants (import, public names, registration,
     subclass, construction) — kept intact from the ATL-03 file.
  2. ATL-24 — SourcePlugin contract: ``test_connection``,
     ``list_documents``, ``fetch_document``, ``extract_plain_text``,
     ``aclose``, plus :class:`DocRef` and :class:`RawDocument` shape
     against frozen fixtures.
  3. ATL-41 — lazy story-points field cache: ``/rest/api/3/field`` hit
     exactly once across two ``list_documents`` calls; zero times when a
     YAML override is set.
  4. ATL-31 — ``fetch_attachment`` delegates to
     :meth:`JiraClient.download_attachment`, and ``fetch_document``
     populates ``RawDocument.attachments`` from ``fields.attachment[]``.

The underlying :class:`JiraClient` is mocked via
``unittest.mock.AsyncMock`` — we test plugin semantics, not HTTP.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    RawDocument,
    SourcePlugin,
)
from src.harvester.jira import (
    JiraConfig,
    JiraHarvesterPlugin,
)
from src.harvester.jira.client import JiraAuthError, JiraClient
from src.harvester.registry import create_plugin, registered_source_types


# ── Helpers / fixtures ────────────────────────────────────────────


def _make_plugin(
    *,
    story_points_field: str | None = None,
    project_keys: list[str] | None = None,
) -> tuple[JiraHarvesterPlugin, AsyncMock]:
    """Build a plugin whose ``client`` is a fully-async mock of :class:`JiraClient`.

    Returns ``(plugin, mock_client)`` so individual tests can stub
    method return values directly on the mock.
    """
    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        project_keys=project_keys if project_keys is not None else ["CONN"],
        story_points_field=story_points_field,
    )
    mock_client = AsyncMock(spec=JiraClient)
    plugin = JiraHarvesterPlugin(cfg, client=mock_client)
    return plugin, mock_client


def _jql_page(issues: list[dict], *, next_page_token: str | None = None) -> dict:
    """Build a ``/rest/api/3/search/jql`` (enhanced JQL) response envelope.

    The enhanced JQL contract drops ``total`` / ``startAt`` /
    ``maxResults``; pagination is driven solely by ``nextPageToken``.
    Pass ``next_page_token`` to mark the envelope as non-terminal.
    """
    page: dict = {"issues": issues}
    if next_page_token is not None:
        page["nextPageToken"] = next_page_token
    return page


def _list_issue(
    key: str,
    *,
    summary: str = "Example issue",
    status: str = "In Progress",
    project_key: str | None = None,
    issue_type: str = "Story",
    updated: str = "2026-04-15T09:21:33.123+0000",
) -> dict:
    """Build a minimal JQL-list-shape issue dict.

    Mirrors :data:`src.harvester.jira.issues._LIST_FIELDS` — only the
    fields the plugin actually reads at list time.
    """
    pk = project_key if project_key is not None else key.rsplit("-", 1)[0]
    return {
        "key": key,
        "self": f"https://example.atlassian.net/rest/api/3/issue/{key}",
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "project": {"key": pk},
            "issuetype": {"name": issue_type},
            "updated": updated,
        },
    }


def _full_issue(
    key: str,
    *,
    description_adf: dict | None = None,
    attachments: list[dict] | None = None,
    story_points_field: str | None = None,
    story_points: float | None = None,
) -> dict:
    """Build a full ``/rest/api/3/issue/{key}`` response payload."""
    fields: dict = {
        "summary": f"Summary for {key}",
        "status": {"name": "Done"},
        "issuetype": {"name": "Story"},
        "priority": {"name": "Medium"},
        "project": {"key": key.rsplit("-", 1)[0]},
        "labels": ["phase-1"],
        "created": "2026-04-01T10:00:00.000+0000",
        "updated": "2026-04-15T09:21:33.123+0000",
        "assignee": {"accountId": "a-123", "displayName": "Ada Lovelace"},
        "reporter": {"accountId": "r-456", "displayName": "Grace Hopper"},
        "description": description_adf,
        "attachment": attachments or [],
    }
    if story_points_field is not None and story_points is not None:
        fields[story_points_field] = story_points
    return {
        "key": key,
        "self": f"https://example.atlassian.net/rest/api/3/issue/{key}",
        "fields": fields,
    }


# ── 1. Scaffold invariants (kept from ATL-03 file) ────────────────


def test_jira_module_importable():
    import src.harvester.jira  # noqa: F401


def test_jira_public_names_exported():
    from src.harvester import jira

    for name in (
        "JiraConfig",
        "JiraIssue",
        "JiraClient",
        "IssueExtractor",
        "text_from_adf",
        "build_jql",
        "discover_story_points_field",
        "flatten_issue_fields",
        "JiraHarvesterPlugin",
    ):
        assert hasattr(jira, name), f"Expected {name!r} in src.harvester.jira"


def test_jira_registered_in_plugin_registry():
    assert "jira" in registered_source_types()


def test_plugin_is_source_plugin_subclass():
    assert issubclass(JiraHarvesterPlugin, SourcePlugin)


def test_plugin_is_instantiable():
    cfg = JiraConfig(base_url="https://example.atlassian.net")
    plugin = JiraHarvesterPlugin(cfg)
    assert plugin.SOURCE_TYPE == "jira"


def test_factory_roundtrip_via_registry(monkeypatch):
    """Factory (ATL-25) round-trips; env vars resolved inside."""
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net",
        "project_keys": ["CONN"],
    }
    plugin, closeable = create_plugin("jira", cfg)
    assert isinstance(plugin, JiraHarvesterPlugin)
    assert closeable is None


# ── 2. ATL-24 — test_connection contract ─────────────────────────


async def test_test_connection_healthy_on_myself_success():
    plugin, mock = _make_plugin()
    mock.get_myself.return_value = {
        "accountId": "a-123",
        "displayName": "Ada Lovelace",
        "emailAddress": "ada@example.com",
    }
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy is True
    assert health.source_type == "jira"
    assert "Ada Lovelace" in health.message
    assert health.details["account_id"] == "a-123"
    mock.get_myself.assert_awaited_once()


async def test_test_connection_unhealthy_on_auth_error():
    plugin, mock = _make_plugin()
    mock.get_myself.side_effect = JiraAuthError(
        "Unauthorized", status_code=401
    )
    health = await plugin.test_connection()
    assert health.healthy is False
    assert health.source_type == "jira"
    # Remediation message names both env-var identifiers for the user.
    assert "JIRA_EMAIL" in health.message
    assert "JIRA_API_TOKEN" in health.message


async def test_test_connection_unhealthy_on_generic_error():
    plugin, mock = _make_plugin()
    mock.get_myself.side_effect = RuntimeError("boom")
    health = await plugin.test_connection()
    assert health.healthy is False
    assert "boom" in health.message


# ── 3. ATL-24 — list_documents contract ───────────────────────────


async def test_list_documents_emits_docrefs_with_required_metadata():
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",  # override → no field lookup
        project_keys=["CONN"],
    )
    mock.jql_search.return_value = _jql_page([
        _list_issue("CONN-1", summary="First", status="To Do"),
        _list_issue("CONN-2", summary="Second", status="Done"),
    ])

    refs = await plugin.list_documents()

    assert len(refs) == 2
    assert all(isinstance(r, DocRef) for r in refs)
    first = refs[0]
    assert first.source_id == "CONN-1"
    assert first.title == "First"
    assert first.source_type == "jira"
    # §3.2 list-time metadata keys.
    assert first.metadata == {
        "document_type": "issue",
        "summary": "First",
        "status": "To Do",
        "project_key": "CONN",
        "updated": "2026-04-15T09:21:33.123+0000",
        "issue_type": "Story",
    }
    # modified_at populated from fields.updated.
    assert first.modified_at is not None
    assert first.modified_at.year == 2026


async def test_list_documents_returns_empty_on_no_project_keys():
    """Defensive — an empty ``project_keys`` config yields [] without calling JQL."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=[],
    )
    refs = await plugin.list_documents()
    assert refs == []
    mock.jql_search.assert_not_awaited()


async def test_list_documents_passes_since_to_jql():
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    mock.jql_search.return_value = _jql_page([])
    await plugin.list_documents(since=datetime(2026, 4, 1, 12, 30))
    # First positional arg to jql_search is the JQL string.
    call_args = mock.jql_search.await_args
    jql = call_args.args[0] if call_args.args else call_args.kwargs["jql"]
    assert 'updated >= "2026-04-01 12:30"' in jql


# ── 4. ATL-41 — lazy story-points field cache ────────────────────


async def test_list_documents_discovers_story_points_field_once():
    """/rest/api/3/field must be hit exactly once across repeated calls."""
    plugin, mock = _make_plugin(story_points_field=None, project_keys=["CONN"])
    mock.list_fields.return_value = [
        {"id": "customfield_10026", "name": "Story point estimate"}
    ]
    mock.jql_search.return_value = _jql_page([])

    await plugin.list_documents()
    await plugin.list_documents()

    assert mock.list_fields.await_count == 1
    assert plugin._story_points_field == "customfield_10026"


async def test_list_documents_skips_discovery_when_override_set():
    """YAML override must short-circuit ``/rest/api/3/field`` entirely."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_99999",
        project_keys=["CONN"],
    )
    mock.jql_search.return_value = _jql_page([])

    await plugin.list_documents()
    await plugin.list_documents()

    mock.list_fields.assert_not_awaited()
    assert plugin._story_points_field == "customfield_99999"


async def test_list_documents_does_not_retry_discovery_when_no_field_found():
    """The ``_discovered`` flag memoises ``None`` results too (ATL-41)."""
    plugin, mock = _make_plugin(story_points_field=None, project_keys=["CONN"])
    mock.list_fields.return_value = []  # site has no story-points field
    mock.jql_search.return_value = _jql_page([])

    await plugin.list_documents()
    await plugin.list_documents()

    assert mock.list_fields.await_count == 1
    assert plugin._story_points_field is None


async def test_list_documents_tolerates_field_listing_failure():
    """If ``/rest/api/3/field`` 403s, we proceed with story_points=None."""
    plugin, mock = _make_plugin(story_points_field=None, project_keys=["CONN"])
    mock.list_fields.side_effect = JiraAuthError("forbidden", status_code=403)
    mock.jql_search.return_value = _jql_page([])

    refs = await plugin.list_documents()
    assert refs == []
    assert plugin._story_points_field is None
    # Still memoised — second call must not re-hit.
    await plugin.list_documents()
    assert mock.list_fields.await_count == 1


# ── 5. ATL-24 — fetch_document contract ──────────────────────────


async def test_fetch_document_returns_raw_json_bytes():
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _full_issue("CONN-42", story_points_field="customfield_10026", story_points=5.0)
    mock.get_issue.return_value = issue

    doc_ref = DocRef(
        source_id="CONN-42",
        title="Summary for CONN-42",
        source_type="jira",
    )
    raw = await plugin.fetch_document(doc_ref)

    assert isinstance(raw, RawDocument)
    assert raw.source_id == "CONN-42"
    assert raw.format == "json"
    assert isinstance(raw.content, bytes)
    # Content round-trips through JSON.
    decoded = json.loads(raw.content)
    assert decoded["key"] == "CONN-42"
    assert decoded["fields"]["summary"] == "Summary for CONN-42"
    # ADF preserved byte-for-byte in content (no flattening in storage).
    assert "fields" in decoded


async def test_fetch_document_metadata_matches_flatten_issue_fields():
    """RawDocument.metadata must be the §3.2 flat shape with story_points wired in."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _full_issue(
        "CONN-42",
        story_points_field="customfield_10026",
        story_points=8.0,
    )
    mock.get_issue.return_value = issue

    doc_ref = DocRef(source_id="CONN-42", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    # §3.2 required keys.
    assert md["document_type"] == "issue"
    assert md["url"] == "https://example.atlassian.net/browse/CONN-42"
    assert md["project_key"] == "CONN"
    assert md["issue_type"] == "Story"
    assert md["status"] == "Done"
    assert md["priority"] == "Medium"
    assert md["assignee_id"] == "a-123"
    assert md["assignee_name"] == "Ada Lovelace"
    assert md["reporter_id"] == "r-456"
    assert md["reporter_name"] == "Grace Hopper"
    assert md["labels"] == ["phase-1"]
    assert md["story_points"] == 8.0
    assert md["resolved_story_points_field"] == "customfield_10026"
    assert md["attachment_count"] == 0


async def test_fetch_document_populates_attachment_refs():
    """ATL-24 populates :class:`AttachmentRef` list even though ATL-31 hasn't landed."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    attachments_raw = [
        {
            "id": "10001",
            "filename": "design.pdf",
            "content": "https://example.atlassian.net/secure/attachment/10001/design.pdf",
            "mimeType": "application/pdf",
            "size": 12345,
        },
        {
            "id": "10002",
            "filename": "screenshot.png",
            "content": "https://example.atlassian.net/secure/attachment/10002/screenshot.png",
            "mimeType": "image/png",
            "size": 67890,
        },
    ]
    issue = _full_issue(
        "CONN-42",
        attachments=attachments_raw,
        story_points_field="customfield_10026",
        story_points=3.0,
    )
    mock.get_issue.return_value = issue

    doc_ref = DocRef(source_id="CONN-42", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    assert len(raw.attachments) == 2
    att = raw.attachments[0]
    assert isinstance(att, AttachmentRef)
    assert att.source_id == "CONN-42"
    assert att.filename == "design.pdf"
    assert att.url.endswith("/design.pdf")
    assert att.mime_type == "application/pdf"
    assert att.size == 12345
    # attachment_count metadata agrees with the ref list.
    assert raw.metadata["attachment_count"] == 2


async def test_fetch_document_skips_malformed_attachments():
    """Attachments without ``content`` or ``filename`` are silently dropped."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _full_issue(
        "CONN-42",
        attachments=[
            {"filename": "ok.txt", "content": "https://example/ok.txt"},
            {"filename": "no-url.txt"},  # missing content
            {"content": "https://example/no-name"},  # missing filename
        ],
    )
    mock.get_issue.return_value = issue

    doc_ref = DocRef(source_id="CONN-42", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)
    assert [a.filename for a in raw.attachments] == ["ok.txt"]


# ── 7. ATL-31 — fetch_attachment + aclose + mark_harvested ───────


async def test_fetch_attachment_delegates_to_client_download():
    """fetch_attachment returns raw bytes via JiraClient.download_attachment."""
    plugin, mock = _make_plugin()
    mock.download_attachment.return_value = b"\x89PNG\r\n\x1a\nfakepng"

    att = AttachmentRef(
        source_id="CONN-42",
        filename="screenshot.png",
        url="https://example.atlassian.net/secure/attachment/10001/screenshot.png",
        mime_type="image/png",
        size=64,
    )
    data = await plugin.fetch_attachment(att)

    assert data == b"\x89PNG\r\n\x1a\nfakepng"
    mock.download_attachment.assert_awaited_once_with(att.url)


async def test_fetch_attachment_propagates_client_errors():
    """Download failures surface to the orchestrator unchanged."""
    plugin, mock = _make_plugin()
    mock.download_attachment.side_effect = JiraAuthError(
        "Unauthorized", status_code=401
    )
    att = AttachmentRef(
        source_id="CONN-42",
        filename="x.txt",
        url="https://example.atlassian.net/secure/attachment/99/x.txt",
    )
    with pytest.raises(JiraAuthError):
        await plugin.fetch_attachment(att)


async def test_fetch_document_populates_attachment_refs_from_full_issue():
    """End-to-end ATL-31 wiring: get_full_issue attachment[] → AttachmentRef list → bytes.

    Ensures the attachment URL travelling through ``RawDocument.attachments``
    is the same URL that :meth:`fetch_attachment` forwards to the client.
    """
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    attachment_url = (
        "https://example.atlassian.net/rest/api/3/attachment/content/10001"
    )
    issue = _full_issue(
        "CONN-42",
        attachments=[
            {
                "id": "10001",
                "filename": "notes.txt",
                "content": attachment_url,
                "mimeType": "text/plain",
                "size": 4,
            }
        ],
    )
    mock.get_issue.return_value = issue
    mock.download_attachment.return_value = b"hey!"

    doc_ref = DocRef(source_id="CONN-42", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)
    assert len(raw.attachments) == 1
    att = raw.attachments[0]
    assert att.url == attachment_url

    # Orchestrator step: plugin.fetch_attachment(att) → bytes.
    data = await plugin.fetch_attachment(att)
    assert data == b"hey!"
    mock.download_attachment.assert_awaited_once_with(attachment_url)


async def test_aclose_delegates_to_client():
    plugin, mock = _make_plugin()
    await plugin.aclose()
    mock.aclose.assert_awaited_once()


async def test_mark_harvested_is_noop():
    """Phase 1 never writes back to Jira (decisions doc 2026-04-19)."""
    plugin, mock = _make_plugin()
    # Should not raise, and should not call any client method.
    await plugin.mark_harvested("CONN-42", "2026-04-20T00:00:00Z")
    mock.assert_not_awaited()


# ── 8. ATL-56 — fixture-driven contract + shape coverage ─────────
#
# The cases above exercise the plugin against hand-built dicts.  The
# block below re-runs the critical paths against the ATL-55 frozen
# fixtures so the wire-shape we saw from a real Jira Cloud response is
# the shape our plugin consumes — no hand-curated drift.
#
# Fixtures exercised:
#
# - ``jql_search_page1.json`` + ``jql_search_page2.json`` — 10 issues
#   paginated across two pages under the enhanced-JQL contract: page 1
#   carries a ``nextPageToken``, page 2 omits it.
#   ``IssueExtractor.list_issues`` terminates when ``nextPageToken``
#   is absent.
# - ``issue_with_attachments.json`` — CONN-1 with ADF description and
#   two ``fields.attachment`` entries.
# - ``issue_with_adf.json`` — CONN-5 with a rich ADF body (heading,
#   bullet list, code block, mention) and no attachments.
# - ``issue_missing_assignee.json`` — CONN-8 with ``assignee: null``,
#   ``priority: null``, ``labels: []``, ``description: null``.
# - ``fields_list.json`` — ``/rest/api/3/field`` including the
#   ``customfield_10026`` "Story point estimate" the auto-discovery
#   branch expects.


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "jira"


def _load_fixture(name: str):
    """Load and parse a JSON fixture from ``tests/fixtures/jira/``."""
    return json.loads((FIXTURES / name).read_text())


def _paged_jql_search(*pages: dict):
    """Build an AsyncMock ``side_effect`` that paginates ``pages`` by ``next_page_token``.

    The extractor calls ``jql_search(jql, fields=..., next_page_token=T, max_results=Y)``
    — ``T`` is ``None`` on the first call, then the previous response's
    ``nextPageToken`` on each subsequent call.  We key by that token so
    the mock cares only about the cursor — not the exact JQL string or
    field selection — which keeps this wiring robust to unrelated
    JQL/field refactors.

    Chaining: first ``pages[i]``'s ``nextPageToken`` maps to
    ``pages[i+1]``.  The first page is keyed by ``None``.  The last
    page's absence of ``nextPageToken`` terminates the extractor loop.
    """
    by_token: dict[str | None, dict] = {}
    prev_token: str | None = None
    for page in pages:
        by_token[prev_token] = page
        prev_token = page.get("nextPageToken")

    async def _impl(*args, **kwargs):
        token = kwargs.get("next_page_token")
        if token is None and len(args) >= 3:
            token = args[2]
        if token not in by_token:
            raise AssertionError(
                f"Unexpected next_page_token={token!r}; fixtures cover {list(by_token)}"
            )
        return by_token[token]

    return _impl


async def test_list_documents_paginates_across_fixture_pages():
    """JQL pagination terminates cleanly after page 2 using ATL-55 fixtures."""
    page1 = _load_fixture("jql_search_page1.json")
    page2 = _load_fixture("jql_search_page2.json")

    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",  # skip /rest/api/3/field lookup
        project_keys=["CONN"],
    )
    mock.jql_search.side_effect = _paged_jql_search(page1, page2)

    refs = await plugin.list_documents()

    # Every fixture issue surfaces exactly once, in order, across both pages.
    assert [r.source_id for r in refs] == [
        f"CONN-{i}" for i in range(1, 11)
    ]
    assert mock.jql_search.await_count == 2
    # DocRef.metadata per §3.2 list-time subset — verify against a
    # specific fixture issue so renames or shape drift break loudly.
    first = refs[0]
    assert first.title == "Ship harvester MVP"
    assert first.metadata["status"] == "In Progress"
    assert first.metadata["issue_type"] == "Story"
    assert first.metadata["project_key"] == "CONN"
    assert first.metadata["updated"] == "2026-04-18T09:21:33.123+0000"


async def test_list_documents_discovery_uses_fields_list_fixture():
    """ATL-40 discovery picks "Story point estimate" id from the fixture."""
    plugin, mock = _make_plugin(story_points_field=None, project_keys=["CONN"])
    mock.list_fields.return_value = _load_fixture("fields_list.json")
    mock.jql_search.return_value = _jql_page([])

    refs = await plugin.list_documents()

    assert refs == []  # JQL returns nothing, discovery still runs.
    assert plugin._story_points_field == "customfield_10026"
    mock.list_fields.assert_awaited_once()


async def test_fetch_document_with_attachments_fixture():
    """CONN-1 fixture: ADF description + two attachments → two AttachmentRefs + sp=8."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _load_fixture("issue_with_attachments.json")
    mock.get_issue.return_value = issue

    doc_ref = DocRef(
        source_id="CONN-1",
        title="Ship harvester MVP",
        source_type="jira",
    )
    raw = await plugin.fetch_document(doc_ref)

    # Raw content round-trips and preserves the ADF node.
    decoded = json.loads(raw.content)
    assert decoded["key"] == "CONN-1"
    assert decoded["fields"]["description"]["type"] == "doc"

    md = raw.metadata
    assert md["document_type"] == "issue"
    assert md["url"] == "https://example.atlassian.net/browse/CONN-1"
    assert md["project_key"] == "CONN"
    assert md["issue_type"] == "Story"
    assert md["status"] == "In Progress"
    assert md["priority"] == "High"
    assert md["assignee_id"] == "a-lovelace-123"
    assert md["assignee_name"] == "Ada Lovelace"
    assert md["reporter_id"] == "g-hopper-456"
    assert md["labels"] == ["phase-1", "mvp"]
    assert md["story_points"] == 8.0
    assert md["resolved_story_points_field"] == "customfield_10026"
    assert md["attachment_count"] == 2

    # AttachmentRefs land on the RawDocument — the orchestrator owns the
    # download + sharded write (§3.3), so we only check the refs here.
    assert [a.filename for a in raw.attachments] == ["design.pdf", "screenshot.png"]
    assert all(a.source_id == "CONN-1" for a in raw.attachments)
    assert raw.attachments[0].mime_type == "application/pdf"
    assert raw.attachments[1].mime_type == "image/png"
    assert raw.attachments[0].url.endswith("/attachment/content/20001")


async def test_fetch_document_with_adf_fixture_preserves_body():
    """CONN-5 fixture: rich ADF description → bytes include the ADF tree verbatim."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _load_fixture("issue_with_adf.json")
    mock.get_issue.return_value = issue

    doc_ref = DocRef(source_id="CONN-5", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    decoded = json.loads(raw.content)
    # ADF is byte-for-byte preserved — nodes, attrs, text all intact.
    desc = decoded["fields"]["description"]
    assert desc["type"] == "doc"
    node_types = [c["type"] for c in desc["content"]]
    assert node_types == ["heading", "paragraph", "bulletList", "codeBlock"]

    md = raw.metadata
    assert md["attachment_count"] == 0
    assert raw.attachments == []
    assert md["story_points"] == 5.0


async def test_fetch_document_with_missing_assignee_fixture():
    """CONN-8 fixture: null assignee/priority/description must yield None, not error."""
    plugin, mock = _make_plugin(
        story_points_field="customfield_10026",
        project_keys=["CONN"],
    )
    issue = _load_fixture("issue_missing_assignee.json")
    mock.get_issue.return_value = issue

    doc_ref = DocRef(source_id="CONN-8", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    assert md["assignee_id"] is None
    assert md["assignee_name"] is None
    assert md["priority"] is None
    assert md["labels"] == []
    assert md["attachment_count"] == 0
    # Story-points field set on the plugin but the fixture has no value
    # for that customfield → story_points should be None (and the
    # resolved-field-id echo must still be populated so the compiler
    # can distinguish "no points" from "site has no field").
    assert md["story_points"] is None
    assert md["resolved_story_points_field"] == "customfield_10026"

    # description: null → no error during fetch.
    assert raw.attachments == []
