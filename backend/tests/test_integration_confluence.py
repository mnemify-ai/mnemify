"""End-to-end harvest test for the Confluence plugin (ATL-54).

Drives a real :class:`HarvestOrchestrator` against the ATL-50 fixture
set.  No network: :class:`ConfluenceClient` is swapped for a fake
whose methods serve canned JSON from ``tests/fixtures/confluence/``.
:class:`PageExtractor` is kept real so the production code path
(pagination, attachment unwrapping, `since` filter, full-page expand
list) is all exercised.

Mirrors ``tests/test_integration_obsidian.py``:

1. Connection health check passes against the fake space list.
2. Orchestrator run writes raw .html files under ``{raw}/confluence/``.
3. Manifest rows carry source_type=confluence, format=html, and a
   populated content_hash.
4. Attachments land under the sharded
   ``{raw}/confluence/{id[:2]}/{id}/attachments/`` layout and are
   listed in the manifest metadata.
5. A second run with the same fixtures reports zero new harvests
   (two-gate dedup via content_hash + source_modified) and leaves raw
   file mtimes untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.harvester.confluence.models import ConfluenceConfig
from src.harvester.confluence.pages import PageExtractor
from src.harvester.confluence.plugin import ConfluenceHarvesterPlugin
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.orchestrator import HarvestOrchestrator, WriteBackConfig
from src.harvester.raw_store import RawStore

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "confluence"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


# ── Fake Confluence client wired into a real plugin ──────────────


def _make_plugin() -> ConfluenceHarvesterPlugin:
    """Build a :class:`ConfluenceHarvesterPlugin` whose client reads fixtures.

    The plugin is constructed normally so its :class:`PageExtractor`
    binding and attachment-ref assembly run exactly as in production;
    only the underlying :class:`ConfluenceClient` is replaced with a
    :class:`MagicMock` configured to serve canned data.  The extractor
    is rebuilt to close over the fake so both sides of the seam stay
    consistent.
    """
    cfg = ConfluenceConfig(
        base_url="https://example.atlassian.net/wiki",
        space_keys=["ENG"],
    )
    plugin = ConfluenceHarvesterPlugin(cfg)

    # Replace the client with a mock that mirrors the REST API envelopes.
    fake = MagicMock()
    fake.list_spaces = AsyncMock(
        return_value={"results": [{"key": "ENG", "name": "Engineering"}], "size": 1}
    )

    # Load fixtures once — shared across the mock's side-effect callables
    list_envelope = _load("list_pages_response.json")
    ancestors_page = _load("page_with_ancestors.json")
    attachments_page = _load("page_with_attachments.json")
    attachments_envelope = _load("attachments_response.json")
    rich_page = _load("page_xhtml_rich.json")
    malformed_page = _load("page_malformed_body.json")
    empty_envelope = _load("page_empty_space.json")

    # ``list_pages_in_space`` paginates: first call returns the 5-page
    # envelope (shorter than ``_PAGE_SIZE`` → loop exits), subsequent
    # calls return an empty envelope so pagination always terminates.
    page_index = {
        "100": attachments_page,
        "101": ancestors_page,
        "102": rich_page,
        "103": malformed_page,
        "104": _minimal_page("104"),
    }

    async def _list_pages_in_space(
        space_key: str,
        expand: list[str] | None = None,
        start: int = 0,
        limit: int = 100,
    ) -> dict:
        if space_key != "ENG":
            return empty_envelope
        if start == 0:
            return list_envelope
        return empty_envelope

    async def _get_page(page_id: str, expand: list[str] | None = None) -> dict:
        return page_index[page_id]

    async def _list_attachments(page_id: str) -> dict:
        if page_id == "100":
            return attachments_envelope
        return {"results": [], "size": 0}

    att_id_to_filename = {
        a["id"]: a["title"] for a in attachments_envelope["results"]
    }

    async def _download_attachment(url: str) -> bytes:
        # New REST URL pattern: .../child/attachment/{att_id}/download
        # Map the id segment back to the title to load the fixture bytes.
        segments = url.split("?", 1)[0].rstrip("/").split("/")
        if segments[-1] == "download":
            filename = att_id_to_filename[segments[-2]]
        else:
            # Fall back to the legacy /download/attachments/{pageId}/{filename} shape.
            filename = segments[-1]
        path = FIXTURE_DIR / "attachments" / filename
        return path.read_bytes()

    fake.list_pages_in_space = AsyncMock(side_effect=_list_pages_in_space)
    fake.get_page = AsyncMock(side_effect=_get_page)
    fake.list_attachments = AsyncMock(side_effect=_list_attachments)
    fake.download_attachment_content = AsyncMock(side_effect=_download_attachment)
    fake.aclose = AsyncMock(return_value=None)

    plugin.client = fake
    # Rebuild PageExtractor to close over the fake client (the ctor
    # assignment captured the original, pre-swap instance).
    plugin.pages = PageExtractor(fake)
    return plugin


def _minimal_page(page_id: str) -> dict:
    """Placeholder full-page dict for ids without a dedicated fixture.

    The orchestrator still needs a valid ``body.storage.value`` and
    ``version.when``; everything else is optional for the end-to-end
    write path to succeed.  Kept distinct from the list-envelope entry
    so mutating this helper cannot accidentally break
    ``list_pages_response.json`` shape.
    """
    return {
        "id": page_id,
        "type": "page",
        "title": f"Minimal {page_id}",
        "space": {"key": "ENG"},
        "body": {"storage": {"value": f"<p>Minimal body for {page_id}</p>"}},
        "version": {"when": "2026-04-05T11:11:11.000Z", "number": 1},
        "history": {
            "createdDate": "2026-04-05T11:11:11.000Z",
            "createdBy": {"accountId": "acc", "displayName": "Anon"},
        },
        "ancestors": [],
        "metadata": {"labels": {"results": []}},
        "_links": {"webui": f"/spaces/ENG/pages/{page_id}/Minimal"},
    }


@pytest.fixture
def plugin() -> ConfluenceHarvesterPlugin:
    return _make_plugin()


# ── 1. Health check ──────────────────────────────────────────────


async def test_connection_against_fixture_client_is_healthy(plugin):
    health = await plugin.test_connection()
    assert health.healthy, f"Health check failed: {health.message}"
    assert health.source_type == "confluence"


# ── 2-4. Full orchestrator run writes raw html + attachments ─────


def _make_orchestrator(plugin, tmp_path: Path, *, force_full: bool = True):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    orch = HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
        write_back=WriteBackConfig(enabled=False),
        force_full=force_full,
    )
    return orch, manifest, raw_store


async def test_orchestrator_writes_html_raw_files(plugin, tmp_path):
    orch, _, _ = _make_orchestrator(plugin, tmp_path)
    result = await orch.run(source_type="confluence", mode="on_demand")

    assert result.found == 5
    assert result.harvested == 5
    assert result.failed == 0

    # Raw files are .html (confluence format is "html")
    raw_files = sorted((tmp_path / "raw" / "confluence").rglob("*.html"))
    assert len(raw_files) == 5
    # Paths are sharded by first two chars of source_id
    for f in raw_files:
        source_id = f.stem
        assert f.parent.name == source_id[:2]


async def test_orchestrator_manifest_rows_populated(plugin, tmp_path):
    orch, manifest, _ = _make_orchestrator(plugin, tmp_path)
    await orch.run(source_type="confluence", mode="on_demand")

    rows = manifest.get_documents("confluence", status="active")
    assert len(rows) == 5
    for row in rows:
        assert row["source_type"] == "confluence"
        assert row["raw_format"] == "html"
        assert row["raw_path"].endswith(".html")
        assert row["content_hash"] is not None


async def test_orchestrator_writes_attachments_under_sharded_path(plugin, tmp_path):
    orch, manifest, _ = _make_orchestrator(plugin, tmp_path)
    await orch.run(source_type="confluence", mode="on_demand")

    # Page 100 is the only one with attachments in the fixture set.
    att_dir = tmp_path / "raw" / "confluence" / "10" / "100" / "attachments"
    assert att_dir.is_dir(), f"Missing attachment directory: {att_dir}"

    written = sorted(p.name for p in att_dir.iterdir())
    assert len(written) == 2
    # Manifest row carries the attachment index under metadata.attachments
    row = manifest.lookup("confluence", "100")
    assert row is not None
    metadata = json.loads(row["metadata"])
    attachments = metadata.get("attachments") or []
    assert len(attachments) == 2
    filenames = {a["filename"] for a in attachments}
    assert filenames == {"diagram.png", "spec.pdf"}
    for att in attachments:
        # ``local_path`` points into the sharded attachment dir
        assert "/confluence/10/100/attachments/" in att["local_path"]
        assert att["sha256"] is not None
        assert att["size"] > 0


# ── 5. Second run reports unchanged, raw mtimes stable ───────────


async def test_orchestrator_second_run_is_all_unchanged(plugin, tmp_path):
    """Two-gate dedup: same content_hash + same source_modified → skipped."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    def _orch():
        return HarvestOrchestrator(
            plugin=plugin,
            manifest=manifest,
            harvest_logger=log,
            max_concurrent=2,
            raw_store=raw_store,
            force_full=True,  # always list all docs so the per-doc resume gate is what dedups
        )

    result1 = await _orch().run(source_type="confluence", mode="on_demand")
    assert result1.harvested == 5

    raw_files = sorted((tmp_path / "raw" / "confluence").rglob("*.html"))
    mtimes_before = {f: f.stat().st_mtime_ns for f in raw_files}

    result2 = await _orch().run(source_type="confluence", mode="on_demand")

    assert result2.harvested == 0, (
        f"Expected 0 harvested on second run, got {result2.harvested}"
    )
    # Every doc should have been reported as unchanged → skipped
    assert result2.skipped >= 5

    for f, mtime in mtimes_before.items():
        assert f.stat().st_mtime_ns == mtime, (
            f"Raw file {f} was rewritten on the second run"
        )
