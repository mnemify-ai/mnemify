"""Failure-mode + edge-case tests for the Jira plugin (ATL-58).

Covers the gaps not exercised by :mod:`tests.test_jira_plugin` or the
client-level tests:

- 401 / 403 / 429(with ``Retry-After``) surface across the plugin
  boundary as :class:`JiraAuthError` / :class:`JiraAPIError` (the
  tenacity retry loop itself is unit-tested in
  :mod:`tests.test_jira_client`).
- Malformed / null ``fields`` payloads do not crash
  :meth:`JiraHarvesterPlugin.fetch_document` — the
  :func:`flatten_issue_fields` null-safety (``fields.get(k) or {}``)
  is load-bearing.
- A YAML ``story_points_field`` override that points to a field id the
  issue does not contain yields ``story_points=None`` (not a crash),
  and ``resolved_story_points_field`` still echoes the override so the
  compiler can tell "no points" from "no field".
- An empty project (``issues: []``, ``total: 0``) yields
  :data:`[]` from ``list_documents`` and never calls ``get_issue``.

The fixtures under ``tests/fixtures/jira/`` (ATL-55) are the wire-shape
ground truth; a few cases here hand-build *malformed* variants that
Atlassian will never actually emit — the intent is to pin the
plugin's defensive behaviour, not the happy path.

Latent plugin boundary behaviour captured here:

- ``JiraHarvesterPlugin.list_documents`` assumes ``fields.status``,
  ``fields.issuetype``, ``fields.project`` are dicts (or absent / null).
  When any of them is a bare string — which real Atlassian JSON never
  emits, but untyped downstream mocks or a future schema change might —
  the plugin raises :class:`AttributeError`.  We codify this as an
  expect-raises so any future loosening of that contract breaks the
  test deliberately (see the `test_list_documents_bare_string_status…`
  block).  Reported back to the sprint as a minor defensive-coding
  follow-up — **not** patched by this test file.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.harvester import AttachmentRef, DocRef
from src.harvester.jira import JiraConfig, JiraHarvesterPlugin
from src.harvester.jira.client import JiraAPIError, JiraAuthError, JiraClient


FIXTURES = Path(__file__).parent / "fixtures" / "jira"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _make_plugin(
    *,
    story_points_field: str | None = "customfield_10026",
    project_keys: list[str] | None = None,
) -> tuple[JiraHarvesterPlugin, AsyncMock]:
    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        project_keys=project_keys if project_keys is not None else ["CONN"],
        story_points_field=story_points_field,
    )
    mock = AsyncMock(spec=JiraClient)
    return JiraHarvesterPlugin(cfg, client=mock), mock


# ── 1. Auth / API error propagation ──────────────────────────────
#
# The tenacity retry loop itself is already exercised in
# tests/test_jira_client.py (429 with Retry-After header → wait →
# retry → success; 5xx same path).  Here we assert the plugin
# boundary: JiraAuthError and a terminal JiraAPIError must surface to
# the orchestrator unchanged — the plugin never swallows them.


async def test_list_documents_propagates_401_as_auth_error():
    """401 from ``jql_search`` bubbles out of ``list_documents`` untouched."""
    plugin, mock = _make_plugin()
    mock.jql_search.side_effect = JiraAuthError("Unauthorized", status_code=401)
    with pytest.raises(JiraAuthError) as exc:
        await plugin.list_documents()
    assert exc.value.status_code == 401


async def test_list_documents_propagates_403_as_auth_error():
    """403 (scope/permission restrictions) surfaces the same way as 401."""
    plugin, mock = _make_plugin()
    mock.jql_search.side_effect = JiraAuthError("Forbidden", status_code=403)
    with pytest.raises(JiraAuthError) as exc:
        await plugin.list_documents()
    assert exc.value.status_code == 403


async def test_fetch_document_propagates_api_error():
    """A terminal JiraAPIError from ``get_issue`` is not swallowed."""
    plugin, mock = _make_plugin()
    mock.get_issue.side_effect = JiraAPIError("500 on issue fetch", status_code=500)

    doc_ref = DocRef(source_id="CONN-1", title="t", source_type="jira")
    with pytest.raises(JiraAPIError) as exc:
        await plugin.fetch_document(doc_ref)
    assert exc.value.status_code == 500


async def test_fetch_attachment_propagates_429_after_retry_exhaustion():
    """A retry-exhausted 429 surfaces to the orchestrator as JiraAPIError.

    The tenacity decorator on the client retries up to
    ``_MAX_ATTEMPTS`` before re-raising; after exhaustion the
    ``_RetryableJiraError`` (still a JiraAPIError) reaches the plugin,
    which must let it propagate so the orchestrator can mark the
    attachment failed and continue.
    """
    plugin, mock = _make_plugin()
    mock.download_attachment.side_effect = JiraAPIError(
        "429 exhausted", status_code=429
    )
    att = AttachmentRef(
        source_id="CONN-1",
        filename="foo.bin",
        url="https://example.atlassian.net/attachment/content/1",
    )
    with pytest.raises(JiraAPIError) as exc:
        await plugin.fetch_attachment(att)
    assert exc.value.status_code == 429


async def test_test_connection_reports_403_as_unhealthy_not_raise():
    """401/403 on ``/rest/api/3/myself`` must flip ``healthy=False``, not raise."""
    plugin, mock = _make_plugin()
    mock.get_myself.side_effect = JiraAuthError("Forbidden", status_code=403)
    health = await plugin.test_connection()
    assert not health.healthy
    assert "403" in health.message


# ── 2. Malformed / null fields ───────────────────────────────────
#
# Atlassian serialises unassigned / unprioritised as explicit ``null``
# (not missing keys).  The plugin's ``fields.get(k) or {}`` pattern
# handles both — these tests pin the contract so a refactor that
# switches to ``fields.get(k, {})`` (which would misbehave for null)
# breaks loudly.


async def test_fetch_document_handles_missing_fields_key_entirely():
    """An issue payload with no ``fields`` key at all must not crash."""
    plugin, mock = _make_plugin()
    mock.get_issue.return_value = {
        "key": "CONN-99",
        "self": "https://example.atlassian.net/rest/api/3/issue/99",
    }
    doc_ref = DocRef(source_id="CONN-99", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    # Project key falls back to splitting the issue key on "-".
    assert md["project_key"] == "CONN"
    # Everything else surfaces as None / [] / 0 without raising.
    assert md["status"] is None
    assert md["issue_type"] is None
    assert md["assignee_id"] is None
    assert md["labels"] == []
    assert md["attachment_count"] == 0


async def test_fetch_document_handles_null_fields_summary():
    """A null ``fields.summary`` falls back to the DocRef title or source_id.

    The plugin's fallback chain is:
        title = fields.get("summary") or doc_ref.title or doc_ref.source_id
    """
    plugin, mock = _make_plugin()
    mock.get_issue.return_value = {
        "key": "CONN-42",
        "self": "https://example.atlassian.net/rest/api/3/issue/42",
        "fields": {"summary": None},
    }
    doc_ref = DocRef(source_id="CONN-42", title="Fallback Title", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)
    assert raw.title == "Fallback Title"


async def test_fetch_document_handles_null_summary_and_empty_docref_title():
    """When BOTH summary and DocRef.title are falsy, source_id is the last resort."""
    plugin, mock = _make_plugin()
    mock.get_issue.return_value = {
        "key": "CONN-42",
        "self": "https://example.atlassian.net/rest/api/3/issue/42",
        "fields": {"summary": None},
    }
    doc_ref = DocRef(source_id="CONN-42", title="", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)
    assert raw.title == "CONN-42"


async def test_fetch_document_handles_null_assignee_and_priority():
    """``assignee: null`` and ``priority: null`` must surface as ``None``, not error."""
    plugin, mock = _make_plugin()
    mock.get_issue.return_value = _load_fixture("issue_missing_assignee.json")
    doc_ref = DocRef(source_id="CONN-8", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    assert md["assignee_id"] is None
    assert md["assignee_name"] is None
    assert md["priority"] is None


async def test_list_documents_bare_string_status_surfaces_attribute_error():
    """A bare-string ``fields.status`` (Atlassian never emits this shape) crashes.

    This test pins the CURRENT plugin behaviour: when ``fields.status``
    is a string, ``status_obj = fields.get("status") or {}`` short-
    circuits to the string (truthy), and ``status_obj.get("name")``
    raises ``AttributeError``.  The same holds for ``issuetype`` and
    ``project``.

    Flagged upward as a sprint follow-up — see module docstring.  Real
    Atlassian responses never trigger this path; defensive coding
    would be an ergonomic win (e.g. a downstream mock or future schema
    change emitting scalars instead of objects).  Not fixed in this
    test-only track.
    """
    plugin, mock = _make_plugin()
    mock.jql_search.return_value = {
        "issues": [
            {
                "key": "CONN-1",
                "self": "https://example.atlassian.net/rest/api/3/issue/10001",
                "fields": {
                    "summary": "s",
                    # Bare string — Atlassian would send {"name": "Done"}.
                    "status": "Done",
                    "project": {"key": "CONN"},
                    "updated": "2026-04-10T00:00:00.000+0000",
                    "issuetype": {"name": "Story"},
                },
            }
        ],
    }

    with pytest.raises(AttributeError):
        await plugin.list_documents()


# ── 3. Story-points override pointing at absent field ────────────
#
# The YAML override is the escape hatch when a site restricts
# ``/rest/api/3/field``.  If the user configures an id that doesn't
# actually appear on the fetched issue, ``story_points`` must emit
# ``None`` without raising — and ``resolved_story_points_field`` must
# still echo the configured id (compiler distinguishes "no points"
# from "no field").


async def test_fetch_document_story_points_override_missing_from_issue():
    """Override id absent on the issue → story_points=None, still non-crashing."""
    plugin, mock = _make_plugin(story_points_field="customfield_99999")
    # Fixture has customfield_10026 set to 8, but NOT customfield_99999.
    mock.get_issue.return_value = _load_fixture("issue_with_attachments.json")
    doc_ref = DocRef(source_id="CONN-1", title="t", source_type="jira")
    raw = await plugin.fetch_document(doc_ref)

    md = raw.metadata
    assert md["story_points"] is None
    # Override id still echoed back so callers can distinguish.
    assert md["resolved_story_points_field"] == "customfield_99999"


async def test_list_documents_story_points_override_skips_field_listing():
    """Override short-circuits ``/rest/api/3/field`` entirely, even on error paths."""
    plugin, mock = _make_plugin(story_points_field="customfield_99999")
    mock.jql_search.return_value = _load_fixture("jql_search_empty.json")

    await plugin.list_documents()
    mock.list_fields.assert_not_awaited()


# ── 4. Empty project ─────────────────────────────────────────────


async def test_list_documents_empty_project_yields_empty_list():
    """``issues: []`` + ``total: 0`` → empty DocRef list, no get_issue calls."""
    plugin, mock = _make_plugin()
    mock.jql_search.return_value = _load_fixture("jql_search_empty.json")

    refs = await plugin.list_documents()
    assert refs == []
    mock.get_issue.assert_not_awaited()


async def test_list_documents_empty_project_still_runs_story_points_discovery():
    """Even with zero issues, discovery still fires exactly once on first call.

    Rationale: the cache is populated on first ``list_documents``
    regardless of the JQL page size — so a site that starts empty but
    later has issues does not have to re-hit ``/rest/api/3/field`` on
    the first non-empty harvest.
    """
    plugin, mock = _make_plugin(story_points_field=None)
    mock.list_fields.return_value = [
        {"id": "customfield_10026", "name": "Story point estimate"}
    ]
    mock.jql_search.return_value = _load_fixture("jql_search_empty.json")

    await plugin.list_documents()
    mock.list_fields.assert_awaited_once()
    assert plugin._story_points_field == "customfield_10026"
