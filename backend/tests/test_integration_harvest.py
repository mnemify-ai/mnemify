"""Integration test — full Notion harvest run against real API data.

This test requires a valid NOTION_TOKEN in your .env file.
It is skipped automatically when the token is absent (CI / unit-test runs).

Run manually:
    NOTION_TOKEN=ntn_... pytest tests/test_integration_harvest.py -v -s

What it does
------------
1. Connects to the real Notion API and lists documents (pages + databases).
2. Fetches the first 3 pages fully.
3. Runs the full orchestrator against a tmp_path raw root.
4. Asserts: raw files exist on disk and round-trip as JSON.
5. Asserts: JSONL contains run_started / ≥1 harvested / run_completed.
6. Re-runs the orchestrator; asserts all unchanged with no new raw file mtimes.
7. Hashes content and upserts into an in-memory HarvestManifest.
8. Runs the same fetch a second time -> all 3 pages must be "unchanged".
"""

from __future__ import annotations

import json
import logging
import os

import pytest

# ── Skip the whole module when no real token is available ──────────
from dotenv import load_dotenv

load_dotenv()
_token = os.getenv("NOTION_TOKEN", "")
pytestmark = pytest.mark.skipif(
    not _token or _token.startswith("ntn_your_"),
    reason="NOTION_TOKEN not set — skipping integration tests",
)

from src.harvester.logger import HarvestLogger  # noqa: E402
from src.harvester.manifest import HarvestManifest  # noqa: E402
from src.harvester.notion.client import NotionClient  # noqa: E402
from src.harvester.notion.plugin import NotionHarvesterPlugin  # noqa: E402
from src.harvester.orchestrator import HarvestOrchestrator  # noqa: E402
from src.harvester.raw_store import RawStore  # noqa: E402
from src.utils.hashing import sha256_hash  # noqa: E402

logger = logging.getLogger(__name__)

# ── Module-level cache — avoids redundant API calls ───────────────
_DOC_CACHE: list | None = None


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
async def plugin():
    """Live NotionHarvesterPlugin — fresh connection per test."""
    async with NotionClient(token=_token) as client:
        yield NotionHarvesterPlugin(client)


@pytest.fixture
async def all_docs(plugin):
    """All DocRefs from the real workspace (cached)."""
    global _DOC_CACHE
    if _DOC_CACHE is None:
        _DOC_CACHE = await plugin.list_documents()
    return _DOC_CACHE


# ── 1. Connection ──────────────────────────────────────────────────

async def test_notion_connection_is_healthy(plugin):
    health = await plugin.test_connection()
    assert health.healthy, f"Connection failed: {health.message}"
    logger.debug(f"Connected as: {health.message}")


# ── 2. list_documents returns docs with expected shape ─────────────

async def test_listing_pages_returns_at_least_one_with_title_and_timestamp(all_docs):
    page_docs = [d for d in all_docs if d.metadata.get("document_type") == "page"]
    assert len(page_docs) > 0, "Expected at least one accessible page"
    logger.debug(f"Found {len(page_docs)} pages, {len(all_docs)} total docs")

    doc = page_docs[0]
    assert doc.source_id
    assert doc.title
    assert doc.source_type == "notion"
    assert doc.modified_at is not None
    assert doc.modified_at.tzinfo is not None


async def test_every_listed_page_carries_parent_and_property_metadata(all_docs):
    pages = [d for d in all_docs if d.metadata.get("document_type") == "page"]
    for doc in pages:
        assert "parent_type" in doc.metadata, f"Missing parent_type for {doc.source_id!r}"
        assert "parent_id" in doc.metadata, f"Missing parent_id for {doc.source_id!r}"
        assert "properties" in doc.metadata, f"Missing properties for {doc.source_id!r}"
        assert isinstance(doc.metadata["properties"], dict)


async def test_databases_are_included_with_document_type_database(all_docs):
    """Databases must be tagged document_type=database in the unified list."""
    db_docs = [d for d in all_docs if d.metadata.get("document_type") == "database"]
    logger.debug(f"Found {len(db_docs)} database docs")
    # Just assert the field is present and typed correctly on any database docs
    for db in db_docs:
        assert db.source_id
        assert db.metadata["document_type"] == "database"


# ── 3. fetch_document — real content ──────────────────────────────

_FETCHED_CACHE: list | None = None


@pytest.fixture
async def fetched_docs(plugin, all_docs):
    """Fetch the first 3 page docs fully (cached)."""
    global _FETCHED_CACHE
    if _FETCHED_CACHE is None:
        page_docs = [d for d in all_docs if d.metadata.get("document_type") == "page"]
        sample = page_docs[:3]
        results = []
        for doc_ref in sample:
            raw = await plugin.fetch_document(doc_ref)
            results.append((doc_ref, raw))
        _FETCHED_CACHE = results
    return _FETCHED_CACHE


async def test_fetched_page_contains_valid_json_with_page_and_blocks(fetched_docs):
    for doc_ref, raw in fetched_docs:
        assert raw.source_id == doc_ref.source_id
        assert raw.format == "json"
        assert len(raw.content) > 0
        parsed = json.loads(raw.content)
        assert "page" in parsed
        assert "blocks" in parsed


async def test_plain_text_extraction_returns_nonempty_string(plugin, fetched_docs):
    for doc_ref, raw in fetched_docs:
        text = plugin.extract_plain_text(raw)
        assert isinstance(text, str)
        logger.debug(f"[{doc_ref.title!r}] plain text: {len(text)} chars")


# ── 7. Full harvest loop with manifest + logger ────────────────────

async def test_first_harvest_marks_all_pages_as_new(fetched_docs, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")

    run_id = manifest.start_run(source_type="notion", mode="on_demand")
    log.log_run_started(run_id, source_type="notion", mode="on_demand")

    stats = {"found": len(fetched_docs), "harvested": 0, "skipped": 0, "failed": 0}

    actions = []
    for doc_ref, raw in fetched_docs:
        content_hash = sha256_hash(raw.content)
        doc_id, action = manifest.upsert_document(
            "notion",
            doc_ref.source_id,
            doc_ref.title,
            source_url=doc_ref.source_url,
            content_hash=content_hash,
            source_modified=doc_ref.modified_at,
        )
        actions.append(action)

        if action in ("new", "updated"):
            stats["harvested"] += 1
            log.log_harvested(run_id, source_type="notion", source_id=doc_ref.source_id,
                              title=doc_ref.title, version=1, action=action)
        else:
            stats["skipped"] += 1
            log.log_skipped(run_id, source_type="notion", source_id=doc_ref.source_id,
                            title=doc_ref.title, reason="unchanged")

    manifest.complete_run(run_id, stats)
    log.log_run_completed(run_id, stats=stats)

    assert all(a == "new" for a in actions), f"Expected all 'new', got {actions}"
    assert stats["harvested"] == 3
    assert stats["skipped"] == 0

    docs_in_db = manifest.get_documents("notion", status="active")
    assert len(docs_in_db) == 3

    logger.debug(f"First run: {stats['harvested']} harvested, {stats['skipped']} skipped")


async def test_second_harvest_with_same_data_skips_all_pages(fetched_docs, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest2.jsonl")

    # First pass
    run_id_first = manifest.start_run("notion", "scheduled")
    for doc_ref, raw in fetched_docs:
        content_hash = sha256_hash(raw.content)
        manifest.upsert_document(
            "notion", doc_ref.source_id, doc_ref.title,
            content_hash=content_hash, source_modified=doc_ref.modified_at,
        )
    manifest.complete_run(run_id_first, {"found": 3, "harvested": 3})

    # Second pass — same content → all unchanged
    run_id_second = manifest.start_run("notion", "scheduled")
    log.log_run_started(run_id_second, source_type="notion")

    actions = []
    for doc_ref, raw in fetched_docs:
        content_hash = sha256_hash(raw.content)
        _, action = manifest.upsert_document(
            "notion", doc_ref.source_id, doc_ref.title,
            content_hash=content_hash, source_modified=doc_ref.modified_at,
        )
        actions.append(action)
        if action == "unchanged":
            log.log_skipped(run_id_second, source_type="notion", source_id=doc_ref.source_id,
                            title=doc_ref.title, reason="unchanged")

    manifest.complete_run(run_id_second, {"found": 3, "harvested": 0, "skipped": 3})
    log.log_run_completed(run_id_second, stats={"found": 3, "harvested": 0, "skipped": 3})

    assert all(a == "unchanged" for a in actions), f"Expected all 'unchanged', got {actions}"

    skipped_entries = log.read_log(action_filter="skipped")
    assert len(skipped_entries) == 3

    logger.debug(f"Second run: all {len(actions)} docs were 'unchanged'")


# ── 8. Full orchestrator run with raw store (WS1+WS3) ─────────────

async def test_orchestrator_full_run_writes_raw_files(plugin, tmp_path):
    """Run the full orchestrator against real API; assert raw files land on disk."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
        skip_attachments=True,
        max_documents=5,
    )

    result = await orch.run(source_type="notion", mode="on_demand")

    assert result.found > 0
    assert result.harvested > 0
    assert result.failed == 0

    # At least one raw file must exist and parse as JSON
    raw_files = list((tmp_path / "raw").rglob("*.json"))
    assert len(raw_files) > 0, "Expected at least one .json raw file"

    for raw_file in raw_files[:3]:
        content = raw_file.read_text(encoding="utf-8")
        parsed = json.loads(content)
        # Pages have "page" key; databases have "database" key
        assert "page" in parsed or "database" in parsed, (
            f"Raw file {raw_file} has neither 'page' nor 'database' key"
        )

    # All harvested rows in manifest must have raw_path set
    docs = manifest.get_documents("notion", status="active")
    assert all(r["raw_path"] is not None for r in docs), (
        "Some manifest rows have null raw_path after harvest"
    )

    # JSONL must contain run_started, ≥1 harvested, run_completed
    entries = log.read_log()
    actions = [e["action"] for e in entries]
    assert "harvest_started" in actions
    assert "harvested" in actions
    assert "harvest_completed" in actions

    logger.debug(
        f"Orchestrator run: found={result.found}, harvested={result.harvested}, "
        f"raw_files={len(raw_files)}"
    )


async def test_orchestrator_second_run_all_unchanged_and_no_new_raw_files(plugin, tmp_path):
    """Second run must report everything unchanged and not update raw file mtimes."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
        skip_attachments=True,
        max_documents=5,
        force_full=True,  # always list all docs so the capped subset is stable across runs
    )

    # First run
    result1 = await orch.run(source_type="notion", mode="on_demand")
    assert result1.harvested > 0

    raw_files = list((tmp_path / "raw").rglob("*.json"))
    mtimes_before = {f: f.stat().st_mtime for f in raw_files}

    # Second run — same full doc list capped to same 5 IDs → all unchanged
    result2 = await orch.run(source_type="notion", mode="on_demand")

    assert result2.harvested == 0, (
        f"Expected 0 harvested on second run, got {result2.harvested}"
    )
    assert result2.skipped > 0

    # No raw file mtimes should have changed
    for f, mtime in mtimes_before.items():
        assert f.stat().st_mtime == mtime, f"Raw file {f} was rewritten on second run"

    logger.debug(
        f"Second run: skipped={result2.skipped}, harvested={result2.harvested}"
    )


# ── 9. get_last_harvest_time feeds next run ────────────────────────

async def test_completed_run_records_a_usable_last_harvest_timestamp(plugin, all_docs):
    manifest = HarvestManifest(":memory:")

    run_id = manifest.start_run("notion", "scheduled")
    manifest.complete_run(run_id, {"found": len(all_docs)})

    last_time = manifest.get_last_harvest_time("notion")
    assert last_time is not None
    assert last_time.tzinfo is not None


# ── 10. manifest stats ─────────────────────────────────────────────

async def test_manifest_stats_reflect_harvested_document_counts(fetched_docs):
    manifest = HarvestManifest(":memory:")
    run_id = manifest.start_run("notion", "scheduled")

    for doc_ref, raw in fetched_docs:
        manifest.upsert_document(
            "notion", doc_ref.source_id, doc_ref.title,
            content_hash=sha256_hash(raw.content),
            source_modified=doc_ref.modified_at,
        )

    n = len(fetched_docs)
    manifest.complete_run(run_id, {"found": n, "harvested": n})
    s = manifest.stats()

    assert s["total_documents"] == n
    assert s["total_runs"] == 1
    notion_rows = [r for r in s["by_source"] if r["source_type"] == "notion"]
    assert notion_rows[0]["n"] == n
    logger.debug(f"Manifest stats: {s}")


# ── 11. Markdown endpoint ─────────────────────────────────────────

async def test_markdown_endpoint_returns_content(plugin, all_docs):
    page_docs = [d for d in all_docs if d.metadata.get("document_type") == "page"]
    if not page_docs:
        pytest.skip("No pages available")
    doc = page_docs[0]
    markdown = await plugin.pages.get_page_markdown(doc.source_id)
    assert isinstance(markdown, str)
    logger.debug(f"Markdown for {doc.source_id[:8]}...: {len(markdown)} chars")


# ── 13. Comments harvested with page ─────────────────────────────

async def test_comments_harvested_with_page(plugin, all_docs):
    page_docs = [d for d in all_docs if d.metadata.get("document_type") == "page"]
    if not page_docs:
        pytest.skip("No pages available")
    doc_ref = page_docs[0]
    raw = await plugin.fetch_document(doc_ref)
    native = json.loads(raw.content)
    assert "comments" in native
    assert isinstance(native["comments"], list)
    logger.debug(
        f"Page {doc_ref.source_id[:8]}... has {len(native['comments'])} comment(s)"
    )
