"""Unit tests for HarvestOrchestrator (src/harvester/orchestrator.py)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.harvester import AttachmentRef, DocRef, HealthStatus, RawDocument, SourcePlugin
from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.orchestrator import HarvestOrchestrator, HarvestResult

logger = logging.getLogger(__name__)


# ── Mock plugin ────────────────────────────────────────────────────


class MockPlugin(SourcePlugin):
    """Configurable mock plugin for orchestrator testing."""

    def __init__(
        self,
        docs: list[DocRef] | None = None,
        health_ok: bool = True,
        fetch_raises: dict[str, Exception] | None = None,
    ):
        self._docs = docs or []
        self._health_ok = health_ok
        self._fetch_raises = fetch_raises or {}
        self.fetched_ids: list[str] = []

    async def test_connection(self) -> HealthStatus:
        return HealthStatus(
            healthy=self._health_ok,
            source_type="mock",
            message="ok" if self._health_ok else "connection refused",
        )

    async def list_documents(self, since=None) -> list[DocRef]:
        return self._docs

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        if doc_ref.source_id in self._fetch_raises:
            raise self._fetch_raises[doc_ref.source_id]
        self.fetched_ids.append(doc_ref.source_id)
        content = f'{{"page": {{"page_id": "{doc_ref.source_id}"}}, "blocks": []}}'.encode()
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=content,
            format="json",
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        return b""


# ── Fixtures ───────────────────────────────────────────────────────


DT = datetime(2026, 4, 10, tzinfo=timezone.utc)


def make_doc(doc_id: str, title: str = "Test Page") -> DocRef:
    return DocRef(
        source_id=doc_id,
        title=title,
        source_type="mock",
        modified_at=DT,
        metadata={"parent_type": "workspace", "parent_id": "workspace"},
    )


def make_orchestrator(
    plugin: MockPlugin,
    manifest: HarvestManifest,
    log: HarvestLogger,
    max_concurrent: int = 5,
) -> HarvestOrchestrator:
    return HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=max_concurrent,
    )


# ── Full lifecycle ─────────────────────────────────────────────────


async def test_run_executes_full_lifecycle(tmp_path):
    docs = [make_doc("p1", "Page One"), make_doc("p2", "Page Two"), make_doc("p3", "Page Three")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    result = await orch.run(source_type="mock", mode="scheduled")

    assert result.found == 3
    assert result.harvested == 3
    assert result.skipped == 0
    assert result.failed == 0
    assert result.run_id.startswith("run_")
    assert result.duration_sec > 0

    # All 3 docs should now be in manifest
    docs_in_db = manifest.get_documents("mock", status="active")
    assert len(docs_in_db) == 3


async def test_run_records_log_entries(tmp_path):
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    await orch.run(source_type="mock")

    entries = log.read_log()
    actions = [e["action"] for e in entries]
    assert "harvest_started" in actions
    assert "harvested" in actions
    assert "harvest_completed" in actions


# ── Semaphore / concurrency ────────────────────────────────────────


async def test_concurrent_fetching_respects_semaphore_limit(tmp_path):
    """Verify that max_concurrent=2 limits simultaneous fetches."""
    concurrency_log: list[int] = []
    active_count = [0]

    original_fetch = MockPlugin.fetch_document

    async def tracked_fetch(self, doc_ref):
        active_count[0] += 1
        concurrency_log.append(active_count[0])
        await asyncio.sleep(0.01)  # simulate async work
        active_count[0] -= 1
        return await original_fetch(self, doc_ref)

    docs = [make_doc(f"p{i}") for i in range(6)]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    with patch.object(MockPlugin, "fetch_document", tracked_fetch):
        orch = make_orchestrator(plugin, manifest, log, max_concurrent=2)
        await orch.run(source_type="mock")

    # Peak concurrency must never exceed semaphore limit
    assert max(concurrency_log) <= 2


# ── Error handling ─────────────────────────────────────────────────


async def test_failed_document_does_not_stop_the_run(tmp_path):
    """A fetch exception on one doc must not abort the rest."""
    docs = [make_doc("p1"), make_doc("p2"), make_doc("p3")]
    plugin = MockPlugin(
        docs=docs,
        fetch_raises={"p2": RuntimeError("simulated API error")},
    )
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    result = await orch.run(source_type="mock")

    assert result.failed == 1
    assert result.harvested == 2  # p1 and p3 succeed
    assert len(result.errors) == 1
    assert "p2" in result.errors[0]


# ── Deletion detection ─────────────────────────────────────────────


async def test_deletion_detection_marks_missing_documents(tmp_path):
    """Documents in manifest but not returned by source should be marked deleted."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    # Pre-seed manifest with a doc that won't be in the next list_documents
    manifest.upsert_document("mock", "old-page", "Old Page")

    # New run returns only p1
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)

    orch = make_orchestrator(plugin, manifest, log)
    result = await orch.run(source_type="mock")

    assert result.deleted == 1
    row = manifest.lookup("mock", "old-page")
    assert row["harvest_status"] == "deleted_at_source"


# ── HarvestResult summary ──────────────────────────────────────────


def test_harvest_result_summary_returns_readable_output():
    result = HarvestResult(
        run_id="run_abc123",
        source_type="notion",
        found=10,
        harvested=7,
        skipped=2,
        failed=1,
        deleted=0,
        duration_sec=3.5,
        errors=["page-x: timeout"],
    )

    summary = result.summary()

    assert "run_abc123" in summary
    assert "notion" in summary
    assert "found=10" in summary
    assert "harvested=7" in summary
    assert "skipped=2" in summary
    assert "failed=1" in summary
    assert "3.5s" in summary
    assert "errors=1" in summary


def test_harvest_result_summary_no_errors():
    result = HarvestResult(
        run_id="run_001", source_type="notion", found=5, harvested=5
    )
    summary = result.summary()
    # No errors line when errors list is empty
    assert "errors" not in summary


# ── Health check failure ───────────────────────────────────────────


async def test_health_check_failure_raises_runtime_error(tmp_path):
    plugin = MockPlugin(docs=[], health_ok=False)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)

    with pytest.raises(RuntimeError, match="health check failed"):
        await orch.run(source_type="mock")


# ── Second run incremental ────────────────────────────────────────


async def test_second_run_skips_unchanged_documents(tmp_path):
    """Second harvest of same docs should result in all skipped."""
    docs = [make_doc("p1"), make_doc("p2")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)

    # First run
    result1 = await orch.run(source_type="mock")
    assert result1.harvested == 2
    assert result1.skipped == 0

    # Second run — same content, same timestamps
    result2 = await orch.run(source_type="mock")
    assert result2.harvested == 0
    assert result2.skipped == 2


# ── WS1: raw store persistence ──────────────────────────────────


async def test_raw_store_file_written_after_harvest(tmp_path):
    """After a harvest, the raw file must exist at the expected sharded path."""
    from src.harvester.raw_store import RawStore

    docs = [make_doc("abcdef1234567890", "Test Page")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store

    result = await orch.run(source_type="mock")

    assert result.harvested == 1
    expected = raw_store.path_for("mock", "abcdef1234567890", "json")
    assert expected.exists()
    assert expected.read_bytes() != b""


async def test_manifest_raw_path_set_after_harvest(tmp_path):
    """manifest.lookup should have raw_path filled in after a successful harvest."""
    from src.harvester.raw_store import RawStore

    source_id = "aabbccdd11223344"
    docs = [make_doc(source_id)]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store
    await orch.run(source_type="mock")

    row = manifest.lookup("mock", source_id)
    assert row is not None
    assert row["raw_path"] is not None
    assert row["converter_version"] == "0.1.0"
    assert source_id in row["raw_path"]


async def test_raw_store_skipped_when_unchanged(tmp_path):
    """On a second run with unchanged content, raw file mtime must not change."""
    from src.harvester.raw_store import RawStore

    docs = [make_doc("aabbccdd")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store

    await orch.run(source_type="mock")
    raw_path = raw_store.path_for("mock", "aabbccdd", "json")
    mtime_first = raw_path.stat().st_mtime

    # Second run — content unchanged
    result2 = await orch.run(source_type="mock")
    assert result2.skipped == 1
    mtime_second = raw_path.stat().st_mtime
    assert mtime_first == mtime_second


async def test_raw_store_write_failure_counts_as_failed(tmp_path):
    """If the raw write raises OSError, the doc must be counted as failed."""
    from unittest.mock import patch
    from src.harvester.raw_store import RawStore

    docs = [make_doc("aabbccdd")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store

    with patch.object(raw_store, "write", side_effect=OSError("disk full")):
        result = await orch.run(source_type="mock")

    assert result.failed == 1
    assert result.harvested == 0
    assert "disk full" in result.errors[0]


# ── WS2: normalization wire ────────────────────────────────────


async def test_normalize_sidecar_written_after_harvest(tmp_path):
    """When normalized_store is wired, a .md sidecar should exist and be tracked in the manifest."""
    from src.harvester import NormalizedDocument, RawDocument
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    class NormPlugin(MockPlugin):
        def normalize(self, raw: RawDocument) -> NormalizedDocument:
            return NormalizedDocument(
                source_id=raw.source_id,
                title=raw.title,
                markdown="---\ntitle: normed\n---\n\n# hello\n",
                frontmatter={"title": "normed"},
                normalizer_version="0.1.0-test",
            )

    docs = [make_doc("aabbccdd11223344")]
    plugin = NormPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    normalized_store = NormalizedStore(tmp_path / "normalized")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store
    orch.normalized_store = normalized_store

    result = await orch.run(source_type="mock")
    assert result.harvested == 1

    row = manifest.lookup("mock", "aabbccdd11223344")
    assert row["normalized_path"] is not None
    assert row["normalizer_version"] == "0.1.0-test"
    assert row["normalized_format"] == "md"
    sidecar = normalized_store.path_for("mock", "aabbccdd11223344")
    assert sidecar.exists()
    assert sidecar.read_text().startswith("---\n")


async def test_raw_metadata_merged_into_manifest_metadata(tmp_path):
    """Fetch-time RawDocument.metadata must land in documents.metadata JSON.

    Fields like ``space_key``, ``ancestors``, ``labels`` only exist after
    a full fetch — they never live on the list-time DocRef. This test locks
    in the orchestrator's merge behavior so those fields survive into the
    manifest, which is where downstream tiers find them now that the .md
    files no longer carry frontmatter.
    """
    import json as _json

    class RichMetaPlugin(MockPlugin):
        async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
            self.fetched_ids.append(doc_ref.source_id)
            return RawDocument(
                source_id=doc_ref.source_id,
                title=doc_ref.title,
                content=b'{"page": {"page_id": "p1"}, "blocks": []}',
                format="json",
                metadata={
                    "space_key": "ENG",
                    "version_number": 7,
                    "author_name": "Alice",
                    "ancestors": [{"id": "r", "title": "Root"}],
                    "labels": ["draft", "project"],
                    "attachment_count": 2,
                },
            )

    plugin = RichMetaPlugin(docs=[make_doc("p1", "Page One")])
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    await orch.run(source_type="mock")

    row = manifest.lookup("mock", "p1")
    meta = _json.loads(row["metadata"])

    # Fields only available after fetch must be persisted
    assert meta["space_key"] == "ENG"
    assert meta["version_number"] == 7
    assert meta["author_name"] == "Alice"
    assert meta["ancestors"] == [{"id": "r", "title": "Root"}]
    assert meta["labels"] == ["draft", "project"]
    assert meta["attachment_count"] == 2

    # List-time DocRef fields survive the merge
    assert meta["parent_type"] == "workspace"
    assert meta["parent_id"] == "workspace"


async def test_raw_and_normalized_bytes_recorded_in_manifest(tmp_path):
    """raw_bytes = len(raw.content); normalized_bytes = len(md.utf-8)."""
    from src.harvester import NormalizedDocument
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    md_body = "# Hello\n\nBody text here.\n"
    raw_content = b'{"page": {"page_id": "bytes-doc"}, "blocks": []}'

    class BytesPlugin(MockPlugin):
        async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
            return RawDocument(
                source_id=doc_ref.source_id,
                title=doc_ref.title,
                content=raw_content,
                format="json",
            )

        def normalize(self, raw: RawDocument) -> NormalizedDocument:
            return NormalizedDocument(
                source_id=raw.source_id,
                title=raw.title,
                markdown=md_body,
                frontmatter={},
                normalizer_version="0.1.0",
            )

    plugin = BytesPlugin(docs=[make_doc("bytes-doc")])
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    orch.normalized_store = NormalizedStore(tmp_path / "normalized")

    await orch.run(source_type="mock")

    row = manifest.lookup("mock", "bytes-doc")
    assert row["raw_bytes"] == len(raw_content)
    assert row["normalized_bytes"] == len(md_body.encode("utf-8"))

    # And the log's harvested entry carries `bytes`
    harvested = [e for e in log.read_log() if e["action"] == "harvested"]
    assert len(harvested) == 1
    assert harvested[0]["bytes"] == len(raw_content)


async def test_harvest_failed_action_in_log(tmp_path):
    """Fetch failure must emit a {'action': 'harvest_failed', ...} log entry."""
    docs = [make_doc("fail-doc")]
    plugin = MockPlugin(
        docs=docs,
        fetch_raises={"fail-doc": RuntimeError("boom")},
    )
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    orch = make_orchestrator(plugin, manifest, log)
    await orch.run(source_type="mock")

    failed = [e for e in log.read_log() if e["action"] == "harvest_failed"]
    assert len(failed) == 1
    assert failed[0]["id"] == "fail-doc"
    assert "boom" in failed[0]["error"]
    assert "ts" in failed[0]


async def test_normalize_notimplemented_leaves_manifest_null(tmp_path):
    """Plugins that raise NotImplementedError (e.g. Notion) should keep normalized_path NULL."""
    from src.harvester import NormalizedDocument, RawDocument
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    class NotionLikePlugin(MockPlugin):
        def normalize(self, raw: RawDocument) -> NormalizedDocument:
            raise NotImplementedError("Notion keeps the legacy reader path")

    plugin = NotionLikePlugin(docs=[make_doc("aaaaaaaaaaaaaaaa")])
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    orch.normalized_store = NormalizedStore(tmp_path / "normalized")

    result = await orch.run(source_type="mock")
    assert result.harvested == 1
    row = manifest.lookup("mock", "aaaaaaaaaaaaaaaa")
    assert row["normalized_path"] is None
    assert row["normalizer_version"] is None


async def test_normalize_failure_does_not_fail_harvest(tmp_path):
    """A normalizer that raises should log but not flip the doc to failed."""
    from src.harvester import NormalizedDocument, RawDocument
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    class BrokenNormPlugin(MockPlugin):
        def normalize(self, raw: RawDocument) -> NormalizedDocument:
            raise ValueError("malformed input")

    plugin = BrokenNormPlugin(docs=[make_doc("cccccccccccccccc")])
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")
    orch.normalized_store = NormalizedStore(tmp_path / "normalized")

    result = await orch.run(source_type="mock")
    assert result.harvested == 1  # raw persists; normalization is best-effort
    assert result.failed == 0
    row = manifest.lookup("mock", "cccccccccccccccc")
    assert row["raw_path"] is not None
    assert row["normalized_path"] is None


# ── WS3: attachment downloads ──────────────────────────────────


class MockPluginWithAttachments(MockPlugin):
    """MockPlugin that returns one attachment with configurable download behavior."""

    def __init__(self, docs, att_bytes=b"fake attachment", att_raise=None, **kwargs):
        super().__init__(docs=docs, **kwargs)
        self._att_bytes = att_bytes
        self._att_raise = att_raise

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        from src.harvester import AttachmentRef
        doc = await super().fetch_document(doc_ref)
        # Inject one attachment ref
        att_ref = AttachmentRef(
            source_id="block-att-1",
            filename="photo.png",
            url="https://example.com/photo.png",
            mime_type="image/png",
        )
        return RawDocument(
            source_id=doc.source_id,
            title=doc.title,
            content=doc.content,
            format=doc.format,
            attachments=[att_ref],
        )

    async def fetch_attachment(self, att_ref) -> bytes:
        if self._att_raise:
            raise self._att_raise
        return self._att_bytes


async def test_attachment_downloaded_and_saved(tmp_path):
    """Attachment bytes must be saved under the parent doc's attachments dir."""
    from src.harvester.raw_store import RawStore

    source_id = "aabbccdd11223344"
    docs = [make_doc(source_id)]
    plugin = MockPluginWithAttachments(docs=docs, att_bytes=b"PNG data")
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store
    result = await orch.run(source_type="mock")

    assert result.harvested == 1
    # Attachment should be in the shard dir
    att_dir = tmp_path / "raw" / "mock" / source_id[:2] / source_id / "attachments"
    assert att_dir.is_dir()
    att_files = list(att_dir.iterdir())
    assert len(att_files) == 1
    assert att_files[0].read_bytes() == b"PNG data"


async def test_attachment_manifest_stored_in_metadata(tmp_path):
    """After harvest, manifest metadata must contain the attachment list."""
    import json
    from src.harvester.raw_store import RawStore

    source_id = "aabbccdd11223344"
    docs = [make_doc(source_id)]
    plugin = MockPluginWithAttachments(docs=docs, att_bytes=b"PNG data")
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store
    await orch.run(source_type="mock")

    row = manifest.lookup("mock", source_id)
    meta = json.loads(row["metadata"])
    assert "attachments" in meta
    assert len(meta["attachments"]) == 1
    assert meta["attachments"][0]["filename"] == "photo.png"


async def test_attachment_failure_does_not_fail_parent(tmp_path):
    """Per-attachment download failure must not cause the parent doc to fail."""
    from src.harvester.raw_store import RawStore

    source_id = "aabbccdd11223344"
    docs = [make_doc(source_id)]
    plugin = MockPluginWithAttachments(
        docs=docs,
        att_raise=Exception("download error"),
    )
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = make_orchestrator(plugin, manifest, log)
    orch.raw_store = raw_store
    result = await orch.run(source_type="mock")

    # Parent doc still harvested
    assert result.harvested == 1
    assert result.failed == 0


# ── WS5: write-back ────────────────────────────────────────────


async def test_write_back_calls_mark_harvested_on_success(tmp_path):
    """When write_back.enabled, plugin.mark_harvested must be called after upsert."""
    from src.harvester.orchestrator import WriteBackConfig

    mark_calls = []

    docs = [make_doc("aabbccdd")]
    plugin = MockPlugin(docs=docs)
    # Attach a tracking mark_harvested method
    async def mock_mark_harvested(source_id, timestamp, property_name):
        mark_calls.append((source_id, timestamp, property_name))

    plugin.mark_harvested = mock_mark_harvested  # type: ignore[attr-defined]

    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    orch.write_back = WriteBackConfig(enabled=True, property_name="Harvested At")
    result = await orch.run(source_type="mock")

    assert result.harvested == 1
    assert len(mark_calls) == 1
    assert mark_calls[0][0] == "aabbccdd"
    assert mark_calls[0][2] == "Harvested At"


async def test_write_back_not_called_when_unchanged(tmp_path):
    """write-back must be skipped for unchanged documents."""
    from src.harvester.orchestrator import WriteBackConfig

    mark_calls = []
    docs = [make_doc("aabbccdd")]
    plugin = MockPlugin(docs=docs)

    async def mock_mark_harvested(source_id, timestamp, property_name):
        mark_calls.append(source_id)

    plugin.mark_harvested = mock_mark_harvested  # type: ignore[attr-defined]

    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    orch.write_back = WriteBackConfig(enabled=True)

    # First run: harvested
    await orch.run(source_type="mock")
    mark_calls.clear()

    # Second run: unchanged
    result2 = await orch.run(source_type="mock")
    assert result2.skipped == 1
    assert mark_calls == []


async def test_write_back_failure_does_not_fail_document(tmp_path):
    """write-back exception must NOT fail the parent document."""
    from src.harvester.orchestrator import WriteBackConfig

    docs = [make_doc("aabbccdd")]
    plugin = MockPlugin(docs=docs)

    async def failing_mark_harvested(source_id, timestamp, property_name):
        raise RuntimeError("Notion 409")

    plugin.mark_harvested = failing_mark_harvested  # type: ignore[attr-defined]

    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    orch.write_back = WriteBackConfig(enabled=True)
    result = await orch.run(source_type="mock")

    assert result.harvested == 1
    assert result.failed == 0


# ── WS6: dry_run and force_full ───────────────────────────────


async def test_dry_run_skips_all_fetches(tmp_path):
    """In dry_run mode, no documents should be fetched or written."""
    docs = [make_doc("p1"), make_doc("p2")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = make_orchestrator(plugin, manifest, log)
    orch.dry_run = True
    result = await orch.run(source_type="mock")

    assert result.harvested == 0
    assert result.failed == 0
    assert result.skipped == 2
    assert plugin.fetched_ids == []


async def test_force_full_ignores_since(tmp_path):
    """force_full=True must pass since=None to list_documents regardless of prior runs."""
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    # Record since values passed to list_documents
    since_values: list = []
    original_list = plugin.list_documents
    async def tracking_list(since=None):
        since_values.append(since)
        return await original_list(since=since)
    plugin.list_documents = tracking_list  # type: ignore[method-assign]

    # First normal run — sets harvest time in manifest
    orch = make_orchestrator(plugin, manifest, log)
    await orch.run(source_type="mock")
    since_values.clear()

    # Second run with force_full — since must be None
    orch2 = make_orchestrator(plugin, manifest, log)
    orch2.force_full = True
    await orch2.run(source_type="mock")

    assert since_values == [None]


# ── Resume short-circuit (Layer 1) ────────────────────────────────


def _orch_with_stores(plugin, manifest, log, tmp_path, *, force_full=False, source_type="mock"):
    """Construct an orchestrator with real raw + normalized stores so
    raw_path is populated after a run — required for the Layer 1 skip
    predicate to fire on subsequent runs."""
    from src.harvester.normalized_store import NormalizedStore
    from src.harvester.raw_store import RawStore

    return HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=1,
        raw_store=RawStore(tmp_path / "raw", converter_version="0.1.0"),
        normalized_store=NormalizedStore(tmp_path / "normalized"),
        force_full=force_full,
    )


async def test_already_harvested_doc_is_skipped_pre_fetch(tmp_path):
    """A doc whose modified_at <= manifest's stored source_modified must
    not trigger plugin.fetch_document — the resume case this layer
    is designed for."""
    docs = [make_doc("p1"), make_doc("p2")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    # First run — both docs harvested into the manifest with raw_path.
    orch = _orch_with_stores(plugin, manifest, log, tmp_path)
    await orch.run(source_type="mock")
    assert sorted(plugin.fetched_ids) == ["p1", "p2"]
    plugin.fetched_ids.clear()

    # Second run with the same modified_at on the listing — neither
    # should be re-fetched.
    orch2 = _orch_with_stores(plugin, manifest, log, tmp_path)
    result = await orch2.run(source_type="mock")
    assert plugin.fetched_ids == []  # ← the key assertion
    assert result.skipped >= 2


async def test_already_harvested_skip_bypassed_for_notion_databases(tmp_path):
    """Notion databases (document_type == 'database') must always
    re-fetch — last_edited_time isn't reliable for them."""
    db_doc = DocRef(
        source_id="db-1",
        title="Tasks",
        source_type="notion",
        modified_at=DT,
        metadata={"document_type": "database", "parent_id": "workspace"},
    )

    class _NotionLikePlugin(MockPlugin):
        async def list_documents(self, since=None):
            return [db_doc]

    plugin = _NotionLikePlugin()
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = _orch_with_stores(plugin, manifest, log, tmp_path, source_type="notion")
    await orch.run(source_type="notion")
    assert plugin.fetched_ids == ["db-1"]
    plugin.fetched_ids.clear()

    # Re-run — database short-circuit must NOT apply; we expect a fetch.
    orch2 = _orch_with_stores(plugin, manifest, log, tmp_path, source_type="notion")
    await orch2.run(source_type="notion")
    assert plugin.fetched_ids == ["db-1"]


async def test_harvest_one_force_full_refetches_unchanged_doc(tmp_path):
    """harvest_one(force_full=True) must re-fetch even when the doc is
    already in the manifest at the same modified_at."""
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = _orch_with_stores(plugin, manifest, log, tmp_path)
    await orch.run(source_type="mock")
    plugin.fetched_ids.clear()

    # Out-of-band reharvest with force_full=True (the default).
    orch2 = _orch_with_stores(plugin, manifest, log, tmp_path)
    result = await orch2.harvest_one(docs[0], force_full=True)
    assert plugin.fetched_ids == ["p1"]
    assert result["action"] == "unchanged"  # content_hash didn't change
    assert result["row"]["source_id"] == "p1"


async def test_harvest_one_without_force_full_short_circuits(tmp_path):
    """harvest_one(force_full=False) honors the resume short-circuit."""
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = _orch_with_stores(plugin, manifest, log, tmp_path)
    await orch.run(source_type="mock")
    plugin.fetched_ids.clear()

    orch2 = _orch_with_stores(plugin, manifest, log, tmp_path)
    result = await orch2.harvest_one(docs[0], force_full=False)
    assert plugin.fetched_ids == []  # short-circuited
    assert result["action"] == "unchanged"


async def test_force_full_bypasses_resume_short_circuit(tmp_path):
    """force_full=True must override the manifest skip and re-fetch all."""
    docs = [make_doc("p1")]
    plugin = MockPlugin(docs=docs)
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "test.jsonl")

    orch = _orch_with_stores(plugin, manifest, log, tmp_path)
    await orch.run(source_type="mock")
    plugin.fetched_ids.clear()

    orch2 = _orch_with_stores(plugin, manifest, log, tmp_path, force_full=True)
    await orch2.run(source_type="mock")
    assert plugin.fetched_ids == ["p1"]
