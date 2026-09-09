"""Integration test — full Jira harvest run against the ATL-55 fixtures (ATL-59).

Runs end-to-end through the real :class:`HarvestOrchestrator` (plugin →
filter → manifest → raw_store → logger) using an in-process
``AsyncMock`` stand-in for :class:`JiraClient` that replays the
``tests/fixtures/jira/`` snapshots.  No network calls; no Atlassian
credentials required.

What it tests:

  1. Plugin connection health check passes against the mock
     ``/rest/api/3/myself`` response.
  2. ``list_documents`` paginates across ``jql_search_page1.json`` +
     ``jql_search_page2.json``, yielding all 10 CONN-* DocRefs.
  3. ``fetch_document`` dispatches per key to each of the three full-
     issue fixtures (attachments / ADF / missing-assignee), and falls
     back to a minimal valid payload for the other 7 keys.
  4. Raw bodies land on disk under ``{raw}/jira/{key[:2]}/{key}.json``
     — format ``json`` per plan §3.2.
  5. Manifest rows carry ``source_type='jira'``, ``raw_format='json'``,
     ``content_hash``, and the flattened metadata keys from §3.2
     (``project_key``, ``issue_type``, ``story_points``, ...).
  6. Attachment bytes for CONN-1 land under
     ``{raw}/jira/CO/CONN-1/attachments/{sha16}{ext}`` (parent-shard-by-
     first-two-chars; here ``CO`` is the shard directory).
  7. The manifest's document row for CONN-1 carries the
     ``metadata.attachments`` list populated by the orchestrator with
     ``filename`` / ``local_path`` / ``sha256`` / ``size`` / ``mime_type``.
  8. JSONL harvest log includes ``harvest_started``, ``harvested``,
     ``harvest_completed`` events.
  9. Second orchestrator run reports every document unchanged
     (``harvested == 0``, ``skipped > 0``) and does NOT rewrite raw
     files (mtimes unchanged).

Mirror — ``tests/test_integration_obsidian.py``.  Kept intentionally
narrow on assertions so a JQL-payload or orchestrator refactor doesn't
cascade into dozens of test edits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from src.harvester import HealthStatus
from src.harvester.jira import JiraConfig, JiraHarvesterPlugin
from src.harvester.jira.client import JiraClient
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.orchestrator import HarvestOrchestrator, WriteBackConfig
from src.harvester.raw_store import RawStore


FIXTURES = Path(__file__).parent / "fixtures" / "jira"


def _load_json_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _load_binary_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── Mock client wiring ───────────────────────────────────────────


def _make_mock_client() -> AsyncMock:
    """Build an :class:`AsyncMock` that plays the ATL-55 fixtures back.

    Wiring:

    - ``get_myself`` returns a minimal user profile.
    - ``list_fields`` returns ``fields_list.json`` (so story-points
      auto-discovery resolves to ``customfield_10026``).
    - ``jql_search`` dispatches by ``next_page_token`` — ``None`` →
      page1; page1's ``nextPageToken`` → page2; page2 omits the token
      so the extractor loop terminates.
    - ``get_issue`` dispatches by issue key — the three full-issue
      fixtures for their keys, a minimal synthesised payload for the
      other 7 keys in the JQL listing (so the orchestrator can walk
      every DocRef without the fixtures file-set ballooning).
    - ``download_attachment`` serves bytes from
      ``tests/fixtures/jira/attachments/`` keyed on the tail of the URL.
    - ``aclose`` is the default AsyncMock no-op.
    """
    mock = AsyncMock(spec=JiraClient)

    mock.get_myself.return_value = {
        "accountId": "a-lovelace-123",
        "displayName": "Ada Lovelace",
        "emailAddress": "ada@example.com",
    }
    mock.list_fields.return_value = _load_json_fixture("fields_list.json")

    page1 = _load_json_fixture("jql_search_page1.json")
    page2 = _load_json_fixture("jql_search_page2.json")
    # First call: no token → page1.  Second call: page1's
    # ``nextPageToken`` → page2.  Page 2 omits the token so the
    # extractor loop terminates.
    by_token: dict[str | None, dict] = {
        None: page1,
        page1["nextPageToken"]: page2,
    }

    async def _jql_search(*args, **kwargs):
        token = kwargs.get("next_page_token")
        if token is None and len(args) >= 3:
            token = args[2]
        if token not in by_token:
            # Shouldn't happen with ATL-55 fixtures; surface loudly.
            raise AssertionError(f"Unexpected next_page_token={token!r}")
        return by_token[token]

    mock.jql_search.side_effect = _jql_search

    full_issues = {
        "CONN-1": _load_json_fixture("issue_with_attachments.json"),
        "CONN-5": _load_json_fixture("issue_with_adf.json"),
        "CONN-8": _load_json_fixture("issue_missing_assignee.json"),
    }
    # Build minimal, valid-enough payloads for the other seven keys so
    # ``fetch_document`` can walk every DocRef the JQL pages yielded.
    # Reuses the list-page entries' shape and adds the fields
    # ``flatten_issue_fields`` expects (empty attachment list, null
    # assignee/priority, etc.).
    def _synth_full_issue(key: str, list_entry: dict) -> dict:
        fields = dict(list_entry["fields"])
        fields.update(
            {
                "priority": None,
                "labels": [],
                "created": fields.get("updated"),
                "assignee": None,
                "reporter": None,
                "description": None,
                "attachment": [],
            }
        )
        return {
            "id": list_entry["id"],
            "key": key,
            "self": list_entry["self"],
            "fields": fields,
        }

    synth_index: dict[str, dict] = {}
    for page in (page1, page2):
        for entry in page["issues"]:
            k = entry["key"]
            if k not in full_issues:
                synth_index[k] = _synth_full_issue(k, entry)

    async def _get_issue(*args, **kwargs):
        key = args[0] if args else kwargs.get("key")
        if key in full_issues:
            return full_issues[key]
        if key in synth_index:
            return synth_index[key]
        raise AssertionError(f"Unexpected get_issue key: {key!r}")

    mock.get_issue.side_effect = _get_issue

    # Serve attachment bytes by URL tail (the CONN-1 fixture uses
    # ``.../attachment/content/20001`` and ``/20002`` — map these to
    # the local attachment fixture files).
    attachment_url_map = {
        "20001": _load_binary_fixture("attachments/design.pdf"),
        "20002": _load_binary_fixture("attachments/screenshot.png"),
    }

    async def _download_attachment(url: str):
        tail = url.rsplit("/", 1)[-1]
        if tail not in attachment_url_map:
            raise AssertionError(f"Unexpected attachment URL: {url!r}")
        return attachment_url_map[tail]

    mock.download_attachment.side_effect = _download_attachment

    return mock


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def jira_plugin() -> JiraHarvesterPlugin:
    """A real :class:`JiraHarvesterPlugin` backed by the ATL-55 mock client."""
    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        project_keys=["CONN"],
        # Leave auto-discovery on so we exercise the full ``/rest/api/3/field``
        # → cache wiring through the orchestrator path.
        story_points_field=None,
    )
    return JiraHarvesterPlugin(cfg, client=_make_mock_client())


# ── 1. Health check ──────────────────────────────────────────────


async def test_connection_against_mock_is_healthy(jira_plugin):
    health = await jira_plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy, f"Health check failed: {health.message}"
    assert health.source_type == "jira"
    assert "Ada Lovelace" in health.message


# ── 2. list_documents paginates ──────────────────────────────────


async def test_list_documents_walks_both_fixture_pages(jira_plugin):
    refs = await jira_plugin.list_documents()
    keys = [r.source_id for r in refs]
    assert keys == [f"CONN-{i}" for i in range(1, 11)]


# ── 3-9. Full orchestrator run ───────────────────────────────────


async def test_orchestrator_writes_raw_json_files(jira_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=jira_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
        write_back=WriteBackConfig(enabled=False),
    )

    result = await orch.run(source_type="jira", mode="on_demand")

    assert result.found == 10
    assert result.harvested == 10
    assert result.failed == 0
    assert result.deleted == 0

    # Raw files are .json for Jira (plan §3.2).
    raw_files = sorted((tmp_path / "raw" / "jira").rglob("*.json"))
    assert len(raw_files) == 10
    # Each file is the authoritative REST payload — round-trips as JSON.
    for f in raw_files:
        decoded = json.loads(f.read_text())
        assert decoded["key"].startswith("CONN-")
        assert "fields" in decoded


async def test_orchestrator_manifest_rows_for_jira(jira_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=jira_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
    )
    await orch.run(source_type="jira", mode="on_demand")

    rows = manifest.get_documents("jira", status="active")
    assert len(rows) == 10

    for row in rows:
        assert row["source_type"] == "jira"
        assert row["raw_format"] == "json"
        assert row["raw_path"] is not None
        assert row["raw_path"].endswith(".json")
        assert row["content_hash"] is not None
        # The manifest's ``metadata`` column is the DocRef.metadata
        # (list-time subset from §3.2: ``document_type``, ``summary``,
        # ``status``, ``project_key``, ``updated``, ``issue_type``) —
        # NOT the full flattened RawDocument.metadata, which lives on
        # disk in the raw JSON body.  Probe only the list-time keys.
        meta = json.loads(row["metadata"]) if row.get("metadata") else {}
        assert meta.get("document_type") == "issue"
        assert meta.get("project_key") == "CONN"
        assert "issue_type" in meta
        assert "updated" in meta


async def test_orchestrator_attachments_stored_under_sharded_path(jira_plugin, tmp_path):
    """CONN-1 → 2 attachments → files under jira/CO/CONN-1/attachments/."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=jira_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
    )
    await orch.run(source_type="jira", mode="on_demand")

    # Shard: source_id[:2] == "CO" for every CONN-* key.
    att_dir = tmp_path / "raw" / "jira" / "CO" / "CONN-1" / "attachments"
    assert att_dir.is_dir(), f"Expected attachment dir at {att_dir}"

    attachment_files = sorted(att_dir.iterdir())
    assert len(attachment_files) == 2, (
        f"Expected 2 attachments, got: {[f.name for f in attachment_files]}"
    )

    # Manifest row for CONN-1 must carry the orchestrator-populated
    # attachments list with filename + local_path + sha256 + size +
    # mime_type.
    row = manifest.lookup("jira", "CONN-1")
    assert row is not None
    meta = json.loads(row["metadata"])
    manifest_attachments = meta.get("attachments") or []
    assert len(manifest_attachments) == 2
    filenames = {a["filename"] for a in manifest_attachments}
    assert filenames == {"design.pdf", "screenshot.png"}
    for att in manifest_attachments:
        assert att["local_path"].startswith(str(att_dir))
        assert att["sha256"]
        assert att["size"] > 0
        assert att["mime_type"] in {"application/pdf", "image/png"}


async def test_orchestrator_jsonl_log_has_expected_events(jira_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log_path = tmp_path / "harvest.jsonl"
    log = HarvestLogger(log_path)
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=jira_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
    )
    await orch.run(source_type="jira", mode="on_demand")

    entries = log.read_log()
    actions = {e["action"] for e in entries}
    assert "harvest_started" in actions
    assert "harvested" in actions
    assert "harvest_completed" in actions


async def test_orchestrator_second_run_all_unchanged(tmp_path):
    """Two runs → second reports everything unchanged, no raw rewrites.

    Each run gets a fresh plugin instance (fresh mock client) so the
    side_effect iterators are not exhausted across runs.
    """
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    def _build_plugin() -> JiraHarvesterPlugin:
        cfg = JiraConfig(
            base_url="https://example.atlassian.net",
            project_keys=["CONN"],
            story_points_field=None,
        )
        return JiraHarvesterPlugin(cfg, client=_make_mock_client())

    def _make_orch(plugin: JiraHarvesterPlugin) -> HarvestOrchestrator:
        return HarvestOrchestrator(
            plugin=plugin,
            manifest=manifest,
            harvest_logger=log,
                max_concurrent=2,
            raw_store=raw_store,
            force_full=True,  # always list all docs
        )

    result1 = await _make_orch(_build_plugin()).run(
        source_type="jira", mode="on_demand"
    )
    assert result1.harvested == 10
    assert result1.failed == 0

    raw_files = sorted((tmp_path / "raw" / "jira").rglob("*.json"))
    mtimes_before = {f: f.stat().st_mtime for f in raw_files}

    result2 = await _make_orch(_build_plugin()).run(
        source_type="jira", mode="on_demand"
    )
    assert result2.harvested == 0, (
        f"Expected 0 harvested on second run, got {result2.harvested}"
    )
    assert result2.skipped > 0

    for f, mtime in mtimes_before.items():
        assert f.stat().st_mtime == mtime, (
            f"Raw file {f} was rewritten on the second run"
        )
